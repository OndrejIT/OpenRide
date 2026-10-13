"""Time offset between two edits of the same ride (e.g. uploaded with and without a burned-in overlay).

Both videos are reduced to "motion energy" of the frame centre over time: camera shake and scenery change are the
same in both, overlays (usually at the edges) and resolution do not matter.
"""

import numpy as np
from scipy.signal import correlate

from pipeline.progress import report

SAMPLE_HZ = 4.0
# centre of the frame; bike computer overlays sit at the edges
CROP_X, CROP_Y = (0.25, 0.75), (0.1, 0.65)
THUMB = (48, 32)
MAX_LAG_S = 300.0
WINDOW_S = 60.0
# a window whose best match is weaker than this has too little motion to tell (standing still, dark tunnel)
MIN_WINDOW_CORR = 0.5
MAX_LAG_DIFF_S = 0.5
MIN_CONSISTENT = 0.8


def motion_energy(path: str, hz: float = SAMPLE_HZ, step: str = "synchronizace verzí videa") -> np.ndarray:
    """Mean absolute difference of consecutive centre thumbnails, sampled at `hz`."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out, prev, nxt = [], None, 0.0
    for i in range(n):
        if not cap.grab():
            break
        if i < nxt:
            continue
        nxt += fps / hz
        report(step, i, n)
        ok, frame = cap.retrieve()
        if not ok:
            continue
        h, w = frame.shape[:2]
        crop = frame[int(CROP_Y[0] * h) : int(CROP_Y[1] * h), int(CROP_X[0] * w) : int(CROP_X[1] * w)]
        thumb = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), THUMB, interpolation=cv2.INTER_AREA).astype(float)
        out.append(0.0 if prev is None else float(np.abs(thumb - prev).mean()))
        prev = thumb
    cap.release()
    if len(out) < 2:
        raise ValueError(f"z videa {path} se nepodařilo přečíst snímky (nepodporovaný kodek?)")
    return np.array(out)


def _z(x: np.ndarray) -> np.ndarray:
    return (x - x.mean()) / (x.std() + 1e-9)


def _ncc(a: np.ndarray, b: np.ndarray, lags: np.ndarray) -> np.ndarray:
    """Correlation of a[i] with b[i + lag] for every lag, normalised over the overlap."""
    a, b = _z(a), _z(b)
    full = correlate(b, a, mode="full")  # index k <-> lag k - (len(a) - 1)
    ones = correlate(np.ones_like(b), np.ones_like(a), mode="full")
    k = lags + len(a) - 1
    ok = (k >= 0) & (k < len(full))
    out = np.full(len(lags), -np.inf)
    out[ok] = full[k[ok]] / np.maximum(ones[k[ok]], 1)
    return out


def offset(data: np.ndarray, play: np.ndarray, hz: float = SAMPLE_HZ) -> dict:
    """Offset [s] with play_time = data_time + offset; fails when the two edits differ.

    The global lag comes from the whole signals, then every minute of the data video is matched on its own: the
    minutes must agree, otherwise the videos are cut differently and one constant offset would be wrong.
    """
    max_lag = int(MAX_LAG_S * hz)
    lags = np.arange(-max_lag, max_lag + 1)
    # short overlaps correlate by chance: require at least half the shorter video to overlap
    overlap = np.minimum(len(data), len(play) - lags) - np.maximum(0, -lags)
    score = np.where(overlap >= min(len(data), len(play)) / 2, _ncc(data, play, lags), -np.inf)
    lag = int(lags[np.argmax(score)])
    win = int(WINDOW_S * hz)
    windows = []
    for start in range(0, len(data) - win + 1, win):
        # each minute searches the whole lag range on its own, so a differently cut part shows up as another lag
        pos = start + lags
        ok = (pos >= 0) & (pos + win <= len(play))
        if not ok.any():
            continue
        c = np.where(ok, _ncc(data[start : start + win], play, pos), -np.inf)
        best = int(np.argmax(c))
        windows.append((start / hz, lags[best] / hz, float(c[best])))
    sure = [(t, lg) for t, lg, c in windows if c >= MIN_WINDOW_CORR]
    agree = [t for t, lg in sure if abs(lg - lag / hz) <= MAX_LAG_DIFF_S]
    result = {
        "offset_s": round(lag / hz, 2),
        "corr": round(float(score.max()), 3),
        "windows": len(windows),
        "windows_sure": len(sure),
        "windows_agree": len(agree),
    }
    if not sure or len(agree) < MIN_CONSISTENT * len(sure):
        off = sorted({round(float(lg), 1) for _, lg in sure})[:10]
        raise ValueError(
            f"videa se neshodují (jinak sestříhaná?): posun {lag / hz:.1f} s sedí jen v {len(agree)} "
            f"z {len(sure)} minut, posuny oken {off}"
        )
    return result


def retime(timing: dict, offset_s: float, duration_s: int) -> dict:
    """Timing of the data video -> timing per second of the played video."""
    t = np.arange(duration_s + 1, dtype=float)
    d = np.interp(t - offset_s, np.asarray(timing["t"], float), np.asarray(timing["dist"], float))
    return {"t": t.astype(int).tolist(), "dist": np.round(d, 1).tolist()}
