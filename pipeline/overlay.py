"""Ride data from a bike computer overlay burned into the video (Garmin style): speed, distance, elevation, grade.

Read once per second (whole frames to find the readouts, then enlarged crops around them); values are recognised
by their units or labels, so no per-channel config is needed: the few ways overlays place them are Layout classes,
one picked per video. The video time -> distance mapping comes straight from the overlay, no alignment.
"""

import json
import logging
import re
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

from pipeline.gpx import build_profile
from pipeline.progress import report

log = logging.getLogger(__name__)

FIELDS = ("speed", "dist", "elev", "grade")
OCR_HZ = 1.0
# a readout moves a little as its digit count changes; other matches farther away are different widgets or misreads
LOC_RADIUS = 0.06  # × frame height
LIMITS = {"speed": (0, 120), "dist": (0, 1000), "elev": (-450, 6000), "grade": (-35, 35)}
# deviation from the local median that marks a misread digit
TOLERANCE = {"speed": 8.0, "dist": 0.3, "elev": 5.0, "grade": 4.0}
VALUE = r"[+-]?\d{1,4}(?:\.\d{1,2})?"
PATTERNS = (
    ("grade", re.compile(r"([+-]?\d{1,2}(?:\.\d)?)%")),  # "+17%" on climbs, "+2.4%" in some overlays
    ("speed", re.compile(r"(\d{1,3}(?:\.\d)?)km/?h")),
    ("dist", re.compile(r"(\d{1,4}(?:\.\d{1,2})?)km")),
    ("elev", re.compile(r"\D*?(-?\d{1,4}(?:\.\d)?)m")),  # also "Höhe1668.2m" when the label merges
)
UNITS = {"%": "grade", "km/h": "speed", "kmh": "speed", "km": "dist", "m": "elev"}
# a label above the value names it when the unit sign is tiny or missing ("SLOPE" over "-5")
LABELS = {
    **dict.fromkeys(("slope", "grade", "gradient", "incline", "steigung", "sklon", "pente", "pendenza"), "grade"),
    **dict.fromkeys(("elevation", "altitude", "alt", "höhe", "hohe", "výška", "vyska", "quota"), "elev"),
}
MERGED = re.compile(r"(?<=km/h)|(?<=kmh)|(?<=rpm)|(?<=%)|(?<=km)(?![/h])|(?<=\dm)(?![a-z/])")
# fewer distance readings than this and the odometer cannot calibrate the speed integral
MIN_DIST_POINTS = 20
# without the speed the odometer alone is the distance: a few scattered readings of it are more likely misreads
ODOMETER_ONLY_COVERAGE = 0.3
CORRECTION_SIGMA_S = 60.0
# odometer step between two readings that the speed cannot explain: the video was cut there
CUT_M = 150.0


Box = tuple[float, float, float, float]
Reading = tuple[str, float, float, float, Box]  # field, value, centre x, centre y, box of value + unit or label


def _items(texts, boxes) -> list[tuple[str, Box]]:
    """Normalised OCR texts with their boxes."""
    items = []
    for text, box in zip(texts, boxes, strict=True):
        b = np.asarray(box, float)
        x0, y0 = b.min(0)
        x1, y1 = b.max(0)
        s = text.lower().replace(" ", "").replace(",", ".").replace("−", "-")  # OCR may return a real minus sign
        # neighbouring readouts may come as one text ("4rpm23km/h2.6km"): each part gets its share of the box
        pos = 0
        for part in filter(None, MERGED.split(s)):
            a, pos = pos, pos + len(part)
            items.append((part, (x0 + (x1 - x0) * a / len(s), y0, x0 + (x1 - x0) * pos / len(s), y1)))
    return items


class Layout:
    """How an overlay places its readouts. A video is read with one layout, picked from its first readable frames
    (pick_layout), so the looser rules one overlay needs cannot misread another."""

    name = "units"

    def unit_fits(self, nbox: Box, ubox: Box, uh: float) -> bool:
        """A separate unit sign belongs to a value left of it or above it ("10" over "km/h")."""
        return (nbox[0] + nbox[2]) / 2 <= (ubox[0] + ubox[2]) / 2 + uh

    def by_label(self, items: list, numbers: list, have: set) -> list[Reading]:
        return []

    def parse(self, texts, boxes) -> list[Reading]:
        """OCR results of one frame -> readings."""
        items = _items(texts, boxes)
        found, numbers, units = [], [], []
        for s, (x0, y0, x1, y1) in items:
            c = ((x0 + x1) / 2, (y0 + y1) / 2)
            if re.fullmatch(VALUE, s):
                numbers.append((float(s), c, y1 - y0, (x0, y0, x1, y1)))
            elif s in UNITS:
                units.append((UNITS[s], c, y1 - y0, (x0, y0, x1, y1)))
            else:
                for field, pat in PATTERNS:
                    if m := pat.fullmatch(s):
                        found.append((field, float(m.group(1)), *c, (x0, y0, x1, y1)))
                        break
        # big readout digits with a separate unit sign
        for field, (ux, uy), uh, ubox in units:
            best = None
            for value, (nx, ny), nh, nbox in numbers:
                dist = np.hypot(ux - nx, uy - ny)
                if (
                    self.unit_fits(nbox, ubox, uh)
                    and ny <= uy + uh
                    and dist < 3 * max(uh, nh)
                    and (best is None or dist < best[0])
                ):
                    box = (min(nbox[0], ubox[0]), min(nbox[1], ubox[1]), max(nbox[2], ubox[2]), max(nbox[3], ubox[3]))
                    best = (dist, value, nx, ny, box)
            if best:
                found.append((field, *best[1:]))
        found += self.by_label(items, numbers, {f for f, *_ in found})
        return [t for t in found if LIMITS[t[0]][0] <= t[1] <= LIMITS[t[0]][1]]

    def tokens(self, texts, boxes) -> list[tuple[str, float, float, float]]:
        """OCR results of one frame -> [(field, value, x, y)] at the value's centre."""
        return [t[:4] for t in self.parse(texts, boxes)]


class LabelledLayout(Layout):
    """Values under their labels, the unit small or left below the value ("ELEVATION" / "2946" / "M"), e.g. the
    Stelvio telemetry: the "%" is mostly too small to read, the label still names the value."""

    name = "labels"

    def unit_fits(self, nbox: Box, ubox: Box, uh: float) -> bool:
        return nbox[0] <= ubox[2] + uh

    def by_label(self, items: list, numbers: list, have: set) -> list[Reading]:
        out = []
        for s, (x0, y0, x1, y1) in items:
            field = LABELS.get(s.rstrip(":"))
            if field is None or field in have:
                continue
            h = y1 - y0
            # the nearest number starting below the label's middle, within two label heights, overlapping it
            below = [n for n in numbers if y0 + h / 2 <= n[3][1] < y1 + 2 * h and n[3][0] < x1 and n[3][2] > x0]
            if below:
                value, (nx, ny), _, nbox = min(below, key=lambda n: n[3][1])
                out.append((field, value, nx, ny, (min(nbox[0], x0), y0, max(nbox[2], x1), nbox[3])))
        return out


# the plain layout first: another one must read clearly more to be picked
LAYOUTS = {layout.name: layout for layout in (Layout(), LabelledLayout())}
PICK_MARGIN = 1.1


def pick_layout(frames: list) -> Layout:
    """The layout reading the most fields in these frames [(texts, boxes)]."""
    best, best_score = None, 0.0
    for layout in LAYOUTS.values():
        score = sum(len({r[0] for r in layout.parse(t, b)}) for t, b in frames)
        if best is None or score > best_score * PICK_MARGIN:
            best, best_score = layout, score
    return best


def layout_of(data: dict) -> Layout:
    """The layout the OCR picked; a cache from before layouts existed picks it again from a sample of its frames."""
    if (name := data.get("layout")) in LAYOUTS:
        return LAYOUTS[name]
    step = max(1, len(data["texts"]) // 300)
    return pick_layout(list(zip(data["texts"][::step], data["boxes"][::step], strict=True)))


# Reading: whole frames until the readouts are located, then only enlarged crops around them (small text reads
# better magnified, and a few small crops are faster than a whole frame); a whole frame every FULL_EVERY_S keeps
# the places up to date. Readouts stay put in these videos, which select() relies on anyway.
CALIBRATION_FRAMES = 30  # whole frames with an overlay before switching to crops
FULL_EVERY_S = 10.0
CROP_SCALE = 2.0


def _place(field: str, xy: np.ndarray, values: np.ndarray, radius: float) -> np.ndarray | None:
    """A readout's usual place: where it is read most often. For the distance the busiest place whose value grows,
    None if none does: overlays also show a lap distance stuck at 0.0 km or the route's total length."""
    rng = np.random.default_rng(0)
    sample = xy[np.sort(rng.choice(len(xy), min(len(xy), 2000), replace=False))]
    density = (np.linalg.norm(sample[:, None] - sample[None], axis=2) < radius).sum(1)
    if field != "dist":
        return sample[np.argmax(density)]
    top = density.max()
    for _ in range(5):  # busiest places first, each farther than a readout's size from the previous ones
        k = np.argmax(density)
        if density[k] < 0.05 * top:
            break
        centre = sample[k]
        near = values[np.linalg.norm(xy - centre, axis=1) < radius]  # in frame order
        m = max(1, len(near) // 10)
        if np.median(near[-m:]) - np.median(near[:m]) >= 0.1:
            return centre
        density[np.linalg.norm(sample - centre, axis=1) < 2 * radius] = -1
    return None


def regions(parsed_frames: list, width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Crop boxes around each readout's usual place (value + unit), padded for changing digit counts; merged."""
    radius = LOC_RADIUS * height
    boxes = []
    for field in FIELDS:
        found = [(v, x, y, box) for frame in parsed_frames for f, v, x, y, box in frame if f == field]
        if not found:
            continue
        xy = np.array([(x, y) for _, x, y, _ in found])
        centre = _place(field, xy, np.array([v for v, *_ in found]), radius)
        if centre is None:
            continue
        near = np.array([box for (_, x, y, box) in found if np.hypot(x - centre[0], y - centre[1]) < radius])
        x0, y0 = near[:, 0].min(), near[:, 1].min()
        x1, y1 = near[:, 2].max(), near[:, 3].max()
        h = y1 - y0
        boxes.append([max(0, x0 - 1.5 * h), max(0, y0 - 0.5 * h), min(width, x1 + 1.5 * h), min(height, y1 + 0.5 * h)])
    merged = []
    for b in sorted(boxes):
        for m in merged:
            if b[0] < m[2] and m[0] < b[2] and b[1] < m[3] and m[1] < b[3]:
                m[:] = [min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])]
                break
        else:
            merged.append(list(b))
    return [tuple(int(round(v)) for v in m) for m in merged]


def ocr(video: Path, hz: float = OCR_HZ) -> dict:
    """Raw OCR of every 1/hz second: {"t": [s], "height": px, "texts": [[str]], "boxes": [[[x0, y0], [x1, y1]]]}.

    Raw text in frame coordinates (crops are mapped back), not parsed values, so a parser fix does not need the
    slow OCR again.
    """
    import time

    import cv2
    from rapidocr import RapidOCR

    engine = RapidOCR(params={"Global.log_level": "error"})  # the models ship with the wheel
    # the detector's default scales every image up to a 736 px short side: a small crop would become huge and slow
    crop_engine = RapidOCR(params={"Global.log_level": "error", "Det.limit_type": "max", "Det.limit_side_len": 960})
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read(img, dx=0.0, dy=0.0, scale=1.0, eng=engine):
        r = eng(img)
        bs = [np.asarray(b, float) / scale + (dx, dy) for b in (r.boxes if r.boxes is not None else ())]
        return list(r.txts or ()), [[np.round(b.min(0), 1).tolist(), np.round(b.max(0), 1).tolist()] for b in bs]

    times, texts, frames, parsed_full = [], [], [], []
    calibration: list = []  # whole frames where some layout reads something, until the layout is picked
    layout: Layout | None = None
    crops: list = []
    nxt, last_full, started, full_count = 0.0, -1e9, time.time(), 0
    for i in range(n):
        if not cap.grab():
            break
        if i < nxt:
            continue
        nxt += fps / hz
        report("OCR overlaye", i, n)
        ok, frame = cap.retrieve()
        if not ok:
            continue
        t = i / fps
        if not crops or t - last_full >= FULL_EVERY_S:
            txt, bx = read(frame)
            last_full, full_count = t, full_count + 1
            if layout is None:
                if any(lay.parse(txt, bx) for lay in LAYOUTS.values()):
                    calibration.append((txt, bx))
                if len(calibration) >= CALIBRATION_FRAMES:
                    layout = pick_layout(calibration)
                    log.info("overlay layout %s", layout.name)
                    parsed_full = [p for p in (layout.parse(*f) for f in calibration) if p]
            elif parsed := layout.parse(txt, bx):
                parsed_full.append(parsed)
            if layout is not None:
                crops = regions(parsed_full, width, height)
        else:
            txt, bx = [], []
            for x0, y0, x1, y1 in crops:
                big = cv2.resize(frame[y0:y1, x0:x1], None, fx=CROP_SCALE, fy=CROP_SCALE, interpolation=cv2.INTER_CUBIC)
                ct, cb = read(big, x0, y0, CROP_SCALE, crop_engine)
                txt += ct
                bx += cb
        texts.append(txt)
        frames.append(bx)
        times.append(round(t, 3))
        if len(times) % 300 == 0:
            log.info("overlay OCR %.0f / %.0f s, %d crops", t, n / fps, len(crops))
    cap.release()
    if not times:
        raise ValueError("z videa se nepodařilo přečíst žádný snímek (nepodporovaný kodek?)")
    return {
        "t": times,
        "height": height,
        "texts": texts,
        "boxes": frames,
        "layout": (layout or pick_layout(calibration)).name,
        "crops": crops,
        "full_frames": full_count,
        "seconds": round(time.time() - started, 1),
    }


def cached_ocr(video: Path, workdir: Path) -> dict:
    """Raw OCR from the cache (or a fresh run); an old cache with parsed tokens is read again from the video."""
    path = workdir / "overlay_ocr.json"
    if path.exists():
        data = json.loads(path.read_text())
        if "texts" in data:
            return data
    data = ocr(video)
    path.write_text(json.dumps(data))
    return data


def frame_tokens(data: dict, layout: Layout) -> list:
    return [layout.tokens(texts, boxes) for texts, boxes in zip(data["texts"], data["boxes"], strict=True)]


def select(frames: list, height: int) -> np.ndarray:
    """Per frame and field the value read at the field's usual place (NaN if missing) -> (frames, FIELDS)."""
    radius = LOC_RADIUS * height
    out = np.full((len(frames), len(FIELDS)), np.nan)
    for k, field in enumerate(FIELDS):
        cands = [(i, v, x, y) for i, toks in enumerate(frames) for f, v, x, y in toks if f == field]
        if not cands:
            continue
        xy = np.array([c[2:] for c in cands])
        centre = _place(field, xy, np.array([c[1] for c in cands]), radius)
        if centre is None:
            continue
        best = np.full(len(frames), radius)
        for (i, v, _, _), dist in zip(cands, np.linalg.norm(xy - centre, axis=1), strict=True):
            if dist < best[i]:
                out[i, k], best[i] = v, dist
    return out


def _clean(x: np.ndarray, tol: float, window: int = 15) -> np.ndarray:
    """Valid samples that agree with their neighbours (drops misread digits, which come in bursts); NaN elsewhere."""
    ok = np.isfinite(x)
    out = np.full_like(x, np.nan)
    if ok.sum() < 3:
        return out
    v = x[ok]
    good = np.abs(v - median_filter(v, window, mode="mirror")) <= tol
    out[np.flatnonzero(ok)[good]] = v[good]
    return out


def _fill(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    ok = np.isfinite(x)
    return np.interp(t, t[ok], x[ok])


def _integrate(t: np.ndarray, kmh: np.ndarray) -> np.ndarray:
    v = _fill(t, kmh) / 3.6
    return np.r_[0, np.cumsum((v[:-1] + v[1:]) / 2 * np.diff(t))]


def distance(t: np.ndarray, speed: np.ndarray, dist_km: np.ndarray) -> tuple[np.ndarray, dict]:
    """Distance [m] at the OCR frame times: speed integral calibrated to the odometer (its 0.1 km steps are too coarse).

    Where the odometer jumps more than the speed explains, the video was cut: the distance jumps at the same frame
    as the elevation, so the profile keeps following the real route.
    """
    have_speed = np.isfinite(speed).mean() >= 0.5
    have_dist = np.isfinite(dist_km).sum() >= MIN_DIST_POINTS
    if not have_speed and (not have_dist or np.isfinite(dist_km).mean() < ODOMETER_ONLY_COVERAGE):
        raise ValueError(
            f"z overlaye se nepodařilo spolehlivě přečíst rychlost ({np.isfinite(speed).mean() * 100:.0f} %) "
            f"ani vzdálenost ({np.isfinite(dist_km).mean() * 100:.0f} %)"
        )
    if not have_dist:
        return _integrate(t, speed), {"dist_scale": None, "cuts_s": []}
    ok = np.isfinite(dist_km)
    odo = dist_km[ok] * 1000
    if not have_speed:
        d = np.maximum.accumulate(gaussian_filter1d(np.interp(t, t[ok], odo), 10.0))
        return d - d[0], {"dist_scale": None, "cuts_s": []}
    integral = _integrate(t, speed)
    s = integral[ok]
    # first reading after each cut; on the running maximum, a low misread and the next good reading are no jump
    cut = np.flatnonzero(np.diff(np.maximum.accumulate(odo)) - np.diff(s) > CUT_M) + 1
    fseg = np.searchsorted(t[ok][cut], t, side="right")  # segment of every frame
    seg = fseg[ok]
    n = len(cut) + 1
    keep = np.ones(len(odo), bool)
    for _ in range(3):  # robust fit, one scale and an offset per segment; drops odometer misreads
        cnt = np.maximum(np.bincount(seg, keep, n), 1)
        xm, ym = np.bincount(seg, keep * s, n) / cnt, np.bincount(seg, keep * odo, n) / cnt
        x, y = s - xm[seg], odo - ym[seg]
        a = np.sum(keep * x * y) / max(np.sum(keep * x * x), 1e-9)
        b = ym - a * xm
        res = odo - (a * s + b[seg])
        keep = np.abs(res) <= max(3 * np.median(np.abs(res[keep])), 100.0)
    corr = np.zeros_like(t)
    tk = t[ok]
    for k in range(n):
        # slow drift between wheel speed and odometer (rounding, pauses in the overlay), never across a cut
        fm, rm = fseg == k, keep & (seg == k)
        if rm.sum() >= 2:
            corr[fm] = gaussian_filter1d(np.interp(t[fm], tk[rm], res[rm]), CORRECTION_SIGMA_S / OCR_HZ)
    d = np.maximum.accumulate(a * integral + b[fseg] + corr)
    info = {
        "dist_scale": round(float(a), 3),
        "dist_rmse_m": round(float(np.sqrt(np.mean(res[keep] ** 2))), 1),
        "cuts_s": [round(float(c)) for c in tk[cut]],
    }
    return d - d[0], info


def ride(t, values: np.ndarray) -> tuple[dict, np.ndarray, dict]:
    """Per-frame overlay values -> (profile, distance per whole video second, quality)."""
    t = np.asarray(t, float)
    raw = {f: values[:, k] for k, f in enumerate(FIELDS)}
    coverage = {f: round(float(np.isfinite(raw[f]).mean()), 3) for f in FIELDS}
    clean = {f: _clean(raw[f], TOLERANCE[f]) for f in FIELDS}
    d, info = distance(t, clean["speed"], clean["dist"])
    if d[-1] < 100:
        raise ValueError("vzdálenost z overlaye je kratší než 100 m")
    if np.isfinite(clean["elev"]).mean() >= 0.3:
        elev, elev_source = _fill(t, clean["elev"]), "elev"
    elif np.isfinite(clean["grade"]).mean() >= 0.3:
        g = _fill(t, clean["grade"])
        elev, elev_source = np.r_[0, np.cumsum(g[:-1] / 100 * np.diff(d))], "grade"
    else:
        raise ValueError("z overlaye se nepodařilo přečíst výšku ani sklon")
    moving = np.r_[True, np.diff(d) > 0.5]
    profile = build_profile(d[moving], elev[moving])
    quality = {"method": "overlay", "coverage": coverage, "elev_source": elev_source, **info}
    ok = np.isfinite(clean["grade"])
    if ok.sum() >= 10:
        # overlay grade is whole percent; agreement says whether elevation and distance fit together
        ours = np.interp(d[ok], profile["dist"], profile["grade"])
        quality["grade_corr"] = round(float(np.corrcoef(ours, clean["grade"][ok])[0, 1]), 3)
        quality["grade_mae"] = round(float(np.mean(np.abs(ours - clean["grade"][ok]))), 2)
    seconds = np.arange(0, int(t[-1]) + 1, dtype=float)
    return profile, np.interp(seconds, t, d), quality
