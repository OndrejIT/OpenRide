"""Ride data from a bike computer overlay burned into the video (Garmin style): speed, distance, elevation, grade.

The whole frame is OCR'd once per second; values are recognised by their units, so no per-channel layout config
is needed. The video time -> distance mapping comes straight from the overlay, no alignment.
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
VALUE = r"-?\d{1,4}(?:\.\d{1,2})?"
PATTERNS = (
    ("grade", re.compile(r"(-?\d{1,2})%")),
    ("speed", re.compile(r"(\d{1,3}(?:\.\d)?)km/?h")),
    ("dist", re.compile(r"(\d{1,4}(?:\.\d{1,2})?)km")),
    ("elev", re.compile(r"\D*?(-?\d{1,4}(?:\.\d)?)m")),  # also "Höhe1668.2m" when the label merges
)
UNITS = {"%": "grade", "km/h": "speed", "kmh": "speed", "km": "dist", "m": "elev"}
# fewer distance readings than this and the odometer cannot calibrate the speed integral
MIN_DIST_POINTS = 20
CORRECTION_SIGMA_S = 60.0
# odometer step between two readings that the speed cannot explain: the video was cut there
CUT_M = 150.0


def tokens(texts, boxes) -> list[tuple[str, float, float, float]]:
    """OCR results of one frame -> [(field, value, x, y)] at the value's centre."""
    items = []
    for text, box in zip(texts, boxes, strict=True):
        b = np.asarray(box, float)
        x0, y0 = b.min(0)
        x1, y1 = b.max(0)
        items.append((text.lower().replace(" ", "").replace(",", "."), x0, y0, x1, y1))
    found, numbers, units = [], [], []
    for s, x0, y0, x1, y1 in items:
        c = ((x0 + x1) / 2, (y0 + y1) / 2)
        if re.fullmatch(VALUE, s):
            numbers.append((float(s), c, y1 - y0))
        elif s in UNITS:
            units.append((UNITS[s], c, y1 - y0))
        else:
            for field, pat in PATTERNS:
                if m := pat.fullmatch(s):
                    found.append((field, float(m.group(1)), *c))
                    break
    # big readout digits with a separate unit label next to them or below ("10" over "km/h")
    for field, (ux, uy), uh in units:
        best = None
        for value, (nx, ny), nh in numbers:
            dist = np.hypot(ux - nx, uy - ny)
            if nx <= ux + uh and ny <= uy + uh and dist < 3 * max(uh, nh) and (best is None or dist < best[0]):
                best = (dist, value, nx, ny)
        if best:
            found.append((field, best[1], best[2], best[3]))
    return [t for t in found if LIMITS[t[0]][0] <= t[1] <= LIMITS[t[0]][1]]


def ocr(video: Path, hz: float = OCR_HZ) -> dict:
    """Tokens of every 1/hz second: {"t": [s], "height": px, "frames": [[(field, value, x, y)]]}."""
    import cv2
    from rapidocr import RapidOCR

    engine = RapidOCR(params={"Global.log_level": "warning"})  # the models ship with the wheel
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    times, frames, nxt = [], [], 0.0
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
        r = engine(frame)
        frames.append(tokens(r.txts or (), r.boxes if r.boxes is not None else ()))
        times.append(round(i / fps, 3))
        if len(times) % 300 == 0:
            log.info("overlay OCR %.0f / %.0f s", i / fps, n / fps)
    cap.release()
    if not times:
        raise ValueError("z videa se nepodařilo přečíst žádný snímek (nepodporovaný kodek?)")
    return {"t": times, "height": height, "frames": frames}


def cached_ocr(video: Path, workdir: Path) -> dict:
    path = workdir / "overlay_ocr.json"
    if path.exists():
        return json.loads(path.read_text())
    data = ocr(video)
    path.write_text(json.dumps(data))
    return data


def select(frames: list, height: int) -> np.ndarray:
    """Per frame and field the value read at the field's usual place (NaN if missing) -> (frames, FIELDS)."""
    radius = LOC_RADIUS * height
    out = np.full((len(frames), len(FIELDS)), np.nan)
    rng = np.random.default_rng(0)
    for k, field in enumerate(FIELDS):
        cands = [(i, v, x, y) for i, toks in enumerate(frames) for f, v, x, y in toks if f == field]
        if not cands:
            continue
        xy = np.array([c[2:] for c in cands])
        sample = xy[rng.choice(len(xy), min(len(xy), 2000), replace=False)]
        density = (np.linalg.norm(sample[:, None] - sample[None], axis=2) < radius).sum(1)
        centre = sample[np.argmax(density)]
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
    if not have_speed and not have_dist:
        raise ValueError("z overlaye se nepodařilo přečíst rychlost ani vzdálenost")
    if not have_dist:
        return _integrate(t, speed), {"dist_scale": None, "cuts_s": []}
    ok = np.isfinite(dist_km)
    odo = dist_km[ok] * 1000
    if not have_speed:
        d = np.maximum.accumulate(gaussian_filter1d(np.interp(t, t[ok], odo), 10.0))
        return d - d[0], {"dist_scale": None, "cuts_s": []}
    integral = _integrate(t, speed)
    s = integral[ok]
    cut = np.flatnonzero(np.diff(odo) - np.diff(s) > CUT_M) + 1  # first reading after each cut
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
