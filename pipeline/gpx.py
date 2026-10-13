"""GPX loading, resampling by distance, elevation profile, summaries and map geometry."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

EARTH_R = 6371000
PROFILE_STEP = 10.0
# ~30 m elevation smoothing, same as the prototype (sigma 6 samples at 5 m)
SMOOTH_M = 30.0


@dataclass
class Track:
    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray
    dist: np.ndarray  # cumulative metres along the track

    @property
    def length(self) -> float:
        return float(self.dist[-1])


def parse(data: bytes | str) -> Track:
    """Track points (or route points) with elevation; duplicate positions are dropped."""
    root = ET.fromstring(data)
    pts = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] in ("trkpt", "rtept")]
    rows = []
    for p in pts:
        ele = next((c.text for c in p if c.tag.rsplit("}", 1)[-1] == "ele"), None)
        if ele is not None:
            rows.append((float(p.get("lat")), float(p.get("lon")), float(ele)))
    if len(rows) < 2:
        raise ValueError("GPX neobsahuje alespoň dva body s nadmořskou výškou")
    lat, lon, ele = np.array(rows).T
    dx = np.radians(np.diff(lon)) * np.cos(np.radians(lat[:-1])) * EARTH_R
    dy = np.radians(np.diff(lat)) * EARTH_R
    dist = np.r_[0, np.cumsum(np.hypot(dx, dy))]
    keep = np.r_[True, np.diff(dist) > 0]  # duplicated points break interpolation
    if keep.sum() < 2:
        raise ValueError("GPX nemá žádnou délku")
    return Track(lat[keep], lon[keep], ele[keep], dist[keep])


def resample(track: Track, step: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Grid every `step` metres -> (dist, lat, lon, ele)."""
    g = np.arange(0, track.dist[-1], step)
    return g, *(np.interp(g, track.dist, a) for a in (track.lat, track.lon, track.ele))


def smooth_grade(ele: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    """Smoothed elevation and grade [%] on a regular grid."""
    sm = gaussian_filter1d(ele, SMOOTH_M / step) if len(ele) > 1 else ele
    grade = 100 * np.gradient(sm) / step if len(sm) > 1 else np.zeros_like(sm)
    return sm, grade


def build_profile(dist, elev, lat=None, lon=None, step: float = PROFILE_STEP) -> dict:
    """Profile on a `step` grid starting at dist 0; inputs are any monotonic distance samples."""
    dist = np.asarray(dist, float)
    g = np.arange(0, dist[-1] - dist[0] + 1e-9, step)
    ele = np.interp(g + dist[0], dist, elev)
    sm, grade = smooth_grade(ele, step)
    prof = {
        "step_m": step,
        "dist": np.round(g, 1).tolist(),
        "elev": np.round(sm, 1).tolist(),
        "grade": np.round(grade, 1).tolist(),
    }
    if lat is not None:
        prof["lat"] = np.round(np.interp(g + dist[0], dist, lat), 6).tolist()
        prof["lon"] = np.round(np.interp(g + dist[0], dist, lon), 6).tolist()
    return prof


def track_profile(
    track: Track, start: float = 0.0, end: float | None = None, step: float = PROFILE_STEP
) -> tuple[dict, float]:
    """Profile of the section [start, end] and its offset on the track (profile dist 0 = offset).

    Smoothing runs on the whole track so the cut has no edge effects.
    """
    g, glat, glon, gele = resample(track, step)
    sm, grade = smooth_grade(gele, step)
    end = track.length if end is None else end
    i0 = max(int(np.searchsorted(g, start, side="right")) - 1, 0)
    i1 = min(int(np.searchsorted(g, end)), len(g) - 1)
    sel = slice(i0, i1 + 1)
    prof = {
        "step_m": step,
        "dist": np.round(g[sel] - g[i0], 1).tolist(),
        "elev": np.round(sm[sel], 1).tolist(),
        "grade": np.round(grade[sel], 1).tolist(),
        "lat": np.round(glat[sel], 6).tolist(),
        "lon": np.round(glon[sel], 6).tolist(),
    }
    return prof, float(g[i0])


def summary(profile: dict) -> dict:
    elev = np.asarray(profile["elev"])
    de = np.diff(elev)
    return {
        "distance_km": round(profile["dist"][-1] / 1000, 2),
        "elev_gain_m": round(float(de[de > 0].sum()), 0),
        "elev_loss_m": round(float(-de[de < 0].sum()), 0),
        "max_grade": round(float(max(profile["grade"])), 1),
    }


def simplify(lat, lon, tolerance_m: float = 5.0) -> list[list[float]]:
    """Douglas-Peucker in a local metric projection; keeps the map geometry small."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    if len(lat) < 3:
        return np.round(np.c_[lat, lon], 6).tolist()
    x = np.radians(lon) * np.cos(np.radians(lat.mean())) * EARTH_R
    y = np.radians(lat) * EARTH_R
    keep = np.zeros(len(lat), bool)
    keep[[0, -1]] = True
    stack = [(0, len(lat) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        dx, dy = x[b] - x[a], y[b] - y[a]
        px, py = x[a + 1 : b] - x[a], y[a + 1 : b] - y[a]
        norm = np.hypot(dx, dy)
        d = np.abs(dx * py - dy * px) / norm if norm > 0 else np.hypot(px, py)
        k = int(np.argmax(d))
        if d[k] > tolerance_m:
            m = a + 1 + k
            keep[m] = True
            stack += [(a, m), (m, b)]
    return np.round(np.c_[lat[keep], lon[keep]], 6).tolist()
