"""HTML pieces for the admin: elevation profile, processing progress, quality of the result."""

import time

import numpy as np
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from routes.models import Video

# grade bands [%] -> colour: blue descents, grey flat, orange to red climbs
GRADE_BANDS = ((-6, "#2b6cb0", "< −6 %"), (-2, "#63b3ed", "−6…−2 %"), (2, "#a0aec0", "±2 %"), (6, "#ed8936", "2…6 %"))
GRADE_STEEP = ("#c53030", "> 6 %")
SVG_W, SVG_H, SVG_PAD = 720, 150, 36
SVG_POINTS = 360


def _grade_colour(g: float) -> str:
    return next((c for limit, c, _ in GRADE_BANDS if g < limit), GRADE_STEEP[0])


def profile_svg(profile: dict) -> str:
    """Elevation profile filled by grade band, small enough to inline in the admin page."""
    dist, elev, grade = (np.asarray(profile[k], float) for k in ("dist", "elev", "grade"))
    idx = np.unique(np.linspace(0, len(dist) - 1, min(SVG_POINTS, len(dist))).round().astype(int))
    d, e = dist[idx], elev[idx]
    # grade of each drawn piece = mean over the profile points it covers, so short spikes are not lost visually
    g = [grade[a : max(b, a + 1)].mean() for a, b in zip(idx[:-1], idx[1:], strict=True)]
    lo, hi = float(e.min()), float(e.max())
    span = max(hi - lo, 10.0)
    plot_w, plot_h = SVG_W - SVG_PAD - 8, SVG_H - 28
    x = SVG_PAD + d / max(d[-1], 1.0) * plot_w
    y = 6 + (1 - (e - lo) / span) * (plot_h - 6)
    base = 6 + plot_h
    parts = [
        f'<polygon points="{x[i]:.1f},{base} {x[i]:.1f},{y[i]:.1f} {x[i + 1]:.1f},{y[i + 1]:.1f} '
        f'{x[i + 1]:.1f},{base}" fill="{c}" stroke="{c}" stroke-width="0.6"/>'  # stroke hides antialiasing seams
        for i, c in enumerate(map(_grade_colour, g))
    ]
    line = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(x, y, strict=True))
    parts.append(f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="1.5"/>')
    text = 'font-size="11" fill="currentColor"'
    parts += [
        f'<text x="{SVG_PAD - 4}" y="12" text-anchor="end" {text}>{hi:.0f} m</text>',
        f'<text x="{SVG_PAD - 4}" y="{base}" text-anchor="end" {text}>{lo:.0f} m</text>',
        f'<text x="{SVG_PAD}" y="{SVG_H - 6}" {text}>0 km</text>',
        f'<text x="{SVG_W - 8}" y="{SVG_H - 6}" text-anchor="end" {text}>{d[-1] / 1000:.2f} km</text>',
    ]
    legend = "".join(
        f'<span style="margin-right:12px"><span style="display:inline-block;width:10px;height:10px;'
        f'background:{c};margin-right:4px"></span>{label}</span>'
        for c, label in [(c, lb) for _, c, lb in GRADE_BANDS] + [GRADE_STEEP]
    )
    return (
        f'<svg viewBox="0 0 {SVG_W} {SVG_H}" width="{SVG_W}" style="max-width:100%;height:auto" role="img" '
        f'aria-label="výškový profil">{"".join(parts)}</svg><div style="font-size:11px">{legend}</div>'
    )


def duration_text(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    h, m = divmod(round(seconds / 60), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def progress_text(video: Video) -> str:
    """One line for the list and the detail: what the worker is doing, or how the last run ended."""
    if video.status == Video.Status.QUEUED:
        return "čeká na worker"
    if video.status == Video.Status.PROCESSING:
        p = video.progress or {}
        if not p:
            return "spouští se"
        text = f"{p['step']} {p['pct']:.0f} %"
        elapsed = time.time() - p["since"]
        if 3 <= p["pct"] < 100 and elapsed > 10:
            text += f" · zbývá ~{duration_text(elapsed * (100 - p['pct']) / p['pct'])}"
        if video.started_at:
            text += f" · běží {duration_text((timezone.now() - video.started_at).total_seconds())}"
        return text
    if video.started_at and video.finished_at:
        took = duration_text((video.finished_at - video.started_at).total_seconds())
        return f"{video.get_status_display()} za {took}"
    return video.get_status_display()


GOOD, WARN, BAD = "good", "warn", "bad"
VERDICTS = {GOOD: ("✓ dobré", "#2f855a"), WARN: ("⚠ podezřelé", "#b7791f"), BAD: ("✗ špatné", "#c53030")}


def _verdict(value: float, good: float, warn: float, higher_is_better: bool = True):
    if not higher_is_better:
        value, good, warn = -value, -good, -warn
    return GOOD if value >= good else WARN if value >= warn else BAD


def _pct(x: float) -> str:
    return f"{100 * x:.0f} %"


METHODS = {"dp": "napárování GPX na video", "overlay": "overlay cyklopočítače (OCR)", "video": "sklon z obrazu"}
COVERAGE_LABELS = {"speed": "rychlost", "dist": "km", "elev": "výška", "grade": "sklon"}
LAYOUT_LABELS = {"units": "hodnoty s jednotkami", "labels": "hodnoty pod popisky"}


def quality_rows(q: dict) -> list[tuple[str, str, str | None]]:
    """(label, value, verdict) rows; thresholds from the processed test rides (Deer Creek, Tyrol, Sankt Kassian)."""
    rows, q = [], dict(q)
    if (m := q.pop("method", None)) is not None:
        rows.append(("metoda", METHODS.get(m, m), None))
    if (v := q.pop("turn_corr", None)) is not None:
        rows.append(("korelace zatáček video × GPX", f"{v:.2f}", _verdict(v, 0.6, 0.4)))
    if "start_m" in q and "end_m" in q:
        a, b = q.pop("start_m"), q.pop("end_m")
        rows.append(("úsek GPX", f"km {a / 1000:.2f} – {b / 1000:.2f}", None))
    if (v := q.pop("mean_kmh", None)) is not None:
        rows.append(("průměrná rychlost", f"{v:.1f} km/h", None))
    if (cov := q.pop("coverage", None)) is not None:
        text = ", ".join(f"{COVERAGE_LABELS.get(k, k)} {_pct(v)}" for k, v in cov.items())
        # only what the profile is computed from; the overlay grade is just a cross-check when elevation is read,
        # the odometer only calibrates the speed integral (either of the two carries the distance)
        height = cov.get("grade" if q.get("elev_source") == "grade" else "elev", 1.0)
        worst = min(max(cov.get("speed", 0.0), cov.get("dist", 0.0)), height)
        rows.append(("přečteno z overlaye", text, _verdict(worst, 0.9, 0.7)))
    if (v := q.pop("dist_scale", None)) is not None:
        rows.append(("měřítko rychlost × počítadlo km", f"{v:.3f}", _verdict(abs(1 - v), 0.05, 0.15, False)))
    if (v := q.pop("dist_rmse_m", None)) is not None:
        rows.append(("odchylka od počítadla km", f"{v:.0f} m", _verdict(v, 50, 150, False)))
    if (cuts := q.pop("cuts_s", None)) is not None:
        rows.append(("střihy ve videu (čas)", ", ".join(f"{c // 60}:{c % 60:02d}" for c in cuts) or "žádné", None))
    if (v := q.pop("layout", None)) is not None:
        rows.append(("rozložení overlaye", LAYOUT_LABELS.get(v, v), None))
    if (v := q.pop("elev_source", None)) is not None:
        rows.append(("výška z", {"elev": "výškoměru v overlayi", "grade": "integrovaného sklonu"}.get(v, v), None))
    if (v := q.pop("grade_corr", None)) is not None:
        rows.append(("shoda se sklonem z overlaye", f"{v:.2f}", _verdict(v, 0.8, 0.6)))
    if (v := q.pop("grade_mae", None)) is not None:
        rows.append(("průměrná odchylka sklonu", f"{v:.1f} %", _verdict(v, 2, 4, False)))
    if (v := q.pop("grade_coverage", None)) is not None:
        rows.append(("úseky se sklonem z obrazu", _pct(v), _verdict(v, 0.7, 0.4)))
    if (s := q.pop("sync", None)) is not None:
        ratio = s["windows_agree"] / max(s["windows_sure"], 1)
        text = f"posun {s['offset_s']:+.1f} s, sedí {s['windows_agree']} z {s['windows_sure']} minut"
        rows.append(("shoda přehrávané a zpracované verze", text, _verdict(ratio, 0.9, 0.8)))
    if q:
        rows.append(("ostatní", ", ".join(f"{k}={v}" for k, v in q.items()), None))
    return rows


def quality_table(q: dict | None):
    if not q:
        return "—"
    body = format_html_join(
        "",
        '<tr><td style="padding-right:16px">{}</td><td style="padding-right:16px">{}</td>'
        '<td style="color:{};white-space:nowrap">{}</td></tr>',
        (
            (label, value, VERDICTS[v][1] if v else "inherit", VERDICTS[v][0] if v else "")
            for label, value, v in quality_rows(q)
        ),
    )
    return format_html("<table>{}</table>", body)


def worst_verdict(q: dict | None) -> str | None:
    verdicts = {v for _, _, v in quality_rows(q or {}) if v}
    return next((v for v in (BAD, WARN, GOOD) if v in verdicts), None)
