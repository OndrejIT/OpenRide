"""Align a time-less GPX track to a video: distance from a speed signal, matched on turns (VO yaw vs GPX heading).

1. rigid: start + one speed scale, searched over the whole GPX (turn-rate correlation) on the first RIGID_WINDOW_S
   of the video only: flow speed drifts ~20 % over longer stretches and a single scale then fits nowhere,
2. dp: elastic path (dynamic programming over time x GPX position) starting within ±DP_WINDOW_M of the rigid start;
   the speed signal is only a soft prior. Unrestricted dp can lock onto a similar-looking stretch elsewhere.

Speed input is either absolute (km/h, e.g. OCR of an overlay) or relative (ground flow, unknown scale).
"""

import logging
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

from pipeline.gpx import Track, resample
from pipeline.progress import report

log = logging.getLogger(__name__)

STEP = 5.0
# sign of corr(VO rotation about the camera y axis, compass heading change), verified on both prototype videos
YAW_SIGN = -1.0
DP_WINDOW_M = 300.0
# Tyrol: 180-900 s windows find the start, 120 s locks onto a wrong place, the full 31 min does not fit one scale
RIGID_WINDOW_S = 300
# mean speed range scanned when the speed signal has no absolute scale
RELATIVE_KMH = (8.0, 70.0)


@dataclass
class Grid:
    """GPX resampled every STEP metres with its curvature."""

    g: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray
    curv: np.ndarray  # rad per metre

    @classmethod
    def from_track(cls, track: Track) -> "Grid":
        g, glat, glon, gele = resample(track, STEP)
        gx = np.radians(glon) * np.cos(np.radians(glat.mean())) * 6371000
        gy = np.radians(glat) * 6371000
        heading = np.unwrap(np.arctan2(np.gradient(gx), np.gradient(gy)))  # compass, radians
        heading = gaussian_filter1d(heading, 4)
        return cls(g, glat, glon, gele, np.gradient(heading) / STEP)

    def turn_rate(self, d: np.ndarray, kmh: np.ndarray) -> np.ndarray:
        """GPX heading change per second at positions d (m) for a speed profile in km/h."""
        return np.interp(d, self.g, self.curv) * kmh / 3.6


def speed_per_second(raw: np.ndarray, ts: np.ndarray, duration: float, relative: bool) -> np.ndarray:
    """Per-second median of the speed samples, gaps interpolated, median filtered."""
    raw = np.asarray(raw, float)
    if not np.isfinite(raw).any():
        raise ValueError("rychlost z videa se nepodařilo určit")
    if relative:
        # flow outliers (blur, cars crossing the ROI) -> drop the top percent before smoothing
        raw = np.where(raw > np.nanpercentile(raw, 99), np.nan, raw)
    ok = np.isfinite(raw) & (raw < 120)
    T = int(np.floor(duration)) + 1
    t = np.arange(T, dtype=float)
    sec = np.full(T, np.nan)
    order = np.argsort(ts, kind="stable")
    ts_s, raw_s, ok_s = ts[order], raw[order], ok[order]
    bounds = np.searchsorted(ts_s, np.arange(T + 1))
    for i in range(T):
        v = raw_s[bounds[i] : bounds[i + 1]][ok_s[bounds[i] : bounds[i + 1]]]
        if len(v):
            sec[i] = np.median(v)
    good = np.isfinite(sec)
    if good.sum() < 2:
        raise ValueError("rychlost z videa se nepodařilo určit")
    return median_filter(np.interp(t, t[good], sec[good]), 7 if relative else 5)


def yaw_rate(vo: np.ndarray, fps: float, T: int) -> np.ndarray:
    """Turn signal from VO: rotation about the camera's vertical axis, rad/s per video second."""
    tv = (vo[:, 0] + vo[:, 1]) / 2 / fps
    ry = np.where(np.isfinite(vo[:, 5]), vo[:, 5], 0) / ((vo[:, 1] - vo[:, 0]) / fps)
    return gaussian_filter1d(np.interp(np.arange(T, dtype=float), tv, ry), 2)


def _cumdist(speed: np.ndarray) -> np.ndarray:
    return np.r_[0, np.cumsum((speed[:-1] + speed[1:]) / 2 / 3.6)]


def rigid_search(grid: Grid, speed, yaw, s_lo, s_hi, s_step, ks) -> tuple[float, float, float]:
    """Best (turn correlation, start, scale): start every s_step in [s_lo, s_hi), distance = start + k * vdist."""
    vdist = _cumdist(speed)
    y = YAW_SIGN * (yaw - yaw.mean())
    y_norm = np.linalg.norm(y)
    starts = np.arange(s_lo, s_hi, s_step)
    best = (-np.inf, float(s_lo), float(ks[0]))
    for k in ks:
        kmh = k * speed
        fits = starts[starts + k * vdist[-1] <= grid.g[-1]]
        for c in range(0, len(fits), 1024):
            s0 = fits[c : c + 1024]
            tr = grid.turn_rate(s0[:, None] + k * vdist[None, :], kmh[None, :])
            tr -= tr.mean(1, keepdims=True)
            with np.errstate(invalid="ignore", divide="ignore"):
                sc = (tr @ y) / (np.linalg.norm(tr, axis=1) * y_norm)
            sc = np.nan_to_num(sc, nan=-np.inf)
            j = int(np.argmax(sc))
            if sc[j] > best[0]:
                best = (float(sc[j]), float(s0[j]), float(k))
    return best


def dp_align(grid: Grid, speed, yaw, k, sig_v, lo, hi, s_max, dt=2, step=2.5, vmax_kmh=80, sig_h=0.06):
    """Dynamic programming over (time, GPX position): match heading changes, keep speed near k*speed.

    Positions are restricted to [lo, s_max]: states before lo can never be reached (the path only moves forward).
    """
    T = len(speed)
    s_lo = np.floor(lo / step) * step
    sg = np.arange(s_lo, min(s_max, grid.g[-1]), step)
    Hg = np.cumsum(np.interp(sg, grid.g, grid.curv)) * step
    Hv = YAW_SIGN * np.cumsum(yaw)  # video heading in the GPX's sense, 1 s steps
    tt = np.arange(0, T, dt)
    dHv = Hv[np.minimum(tt + dt, T - 1)] - Hv[tt]
    vprior = np.maximum(k * speed[tt] / 3.6, 0.3)
    maxd = int(np.ceil(vmax_kmh / 3.6 * dt / step))
    S, INF = len(sg), 1e18
    cost = np.where((sg >= lo) & (sg <= hi), 0.0, INF)
    back = np.zeros((len(tt) - 1, S), np.int16)
    for i in range(len(tt) - 1):
        new, arg = np.full(S, INF), np.zeros(S, np.int16)
        for st in range(maxd + 1):
            v = st * step / dt
            c = (
                cost[: S - st]
                + (dHv[i] - (Hg[st:] - Hg[: S - st])) ** 2 / (2 * sig_h**2)
                + np.log((v + 0.5) / (vprior[i] + 0.5)) ** 2 / (2 * sig_v**2)
            )
            better = c < new[st:]
            new[st:][better], arg[st:][better] = c[better], st
        cost, back[i] = new, arg
    j = int(np.argmin(cost))
    path = [j]
    for i in range(len(tt) - 2, -1, -1):
        j -= int(back[i, j])  # int(): j as np.int16 would overflow on long tracks
        path.append(j)
    return np.interp(np.arange(T, dtype=float), tt, sg[np.array(path[::-1])]), float(cost.min())


def align(
    track: Track,
    vo: np.ndarray,
    fps: float,
    speed_raw: np.ndarray,
    speed_t: np.ndarray,
    duration: float,
    relative: bool,
) -> dict:
    """Video second -> GPX distance. speed_raw/speed_t: speed samples (km/h or relative) and their video times [s]."""
    report("napárování na GPX", 0, 2)
    grid = Grid.from_track(track)
    speed = speed_per_second(speed_raw, speed_t, duration, relative)
    T = len(speed)
    yaw = yaw_rate(vo, fps, T)
    end = grid.g[-1]
    rs, ry = speed[:RIGID_WINDOW_S], yaw[:RIGID_WINDOW_S]

    if relative:
        base = 1.0 / speed.mean()
        scales = np.arange(RELATIVE_KMH[0], RELATIVE_KMH[1] + 1e-9, 0.25) * base
        r_score, r_s0, r_k = rigid_search(grid, rs, ry, 0, end, 25, scales)
        dk = scales[1] - scales[0]  # coarse-to-fine
        r_score, r_s0, r_k = rigid_search(
            grid, rs, ry, max(0, r_s0 - 100), r_s0 + 100, STEP, np.linspace(r_k - dk, r_k + dk, 11)
        )
        # flow has no absolute scale and drifts ~20 % -> loose prior around the rigid mean speed
        sig_v = 0.25
        ks = np.arange(-2, 2 + 1e-9, 0.5) * base + r_k
    else:
        r_score, r_s0, r_k = rigid_search(grid, rs, ry, 0, end, STEP, np.arange(0.90, 1.10 + 1e-9, 0.01))
        # absolute speed (OCR) is trusted -> tight prior
        sig_v = 0.1
        ks = np.arange(0.96, 1.041, 0.02)
    report("napárování na GPX", 1, 2)
    rigid_len = r_k * _cumdist(speed)[-1]
    log.info("rigid: start %.0f m, mean %.1f km/h, turn corr %+.2f", r_s0, (r_k * speed).mean(), r_score)

    lo, hi = max(0.0, r_s0 - DP_WINDOW_M), r_s0 + DP_WINDOW_M
    # generous room past the rigid end; the elastic path rarely stretches the segment by more than a third
    s_max = hi + 1.5 * rigid_len + 1000
    d, _, k = min((dp_align(grid, speed, yaw, k, sig_v, lo, hi, s_max) + (k,) for k in ks), key=lambda r: r[1])
    speed_gpx = gaussian_filter1d(np.gradient(d) * 3.6, 2)  # km/h along the GPX
    score = YAW_SIGN * np.corrcoef(grid.turn_rate(d, speed_gpx), yaw)[0, 1]
    log.info("dp: start %.0f m, segment %.2f km, turn corr %+.2f", d[0], (d[-1] - d[0]) / 1000, score)
    return {
        "t": np.arange(T, dtype=float),
        "d": d,
        "speed": speed_gpx,
        "yaw": yaw,
        "quality": {
            "method": "dp",
            "speed_source": "flow" if relative else "absolute",
            "turn_corr": round(float(score), 3),
            "start_m": round(float(d[0]), 1),
            "end_m": round(float(d[-1]), 1),
            "mean_kmh": round(float(speed_gpx.mean()), 1),
            "prior_scale": float(k),
            "rigid_turn_corr": round(float(r_score), 3),
            "rigid_start_m": round(float(r_s0), 1),
            "rigid_mean_kmh": round(float((r_k * speed).mean()), 1),
        },
    }
