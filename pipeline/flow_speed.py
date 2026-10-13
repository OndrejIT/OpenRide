"""Relative ground speed from road flow: de-rotated KLT flow of ground points, normalised by ground-plane geometry.

For a camera at fixed height moving forward, a ground point's translational flow is ~ v/h * |p - foe| * (y - y_foe);
dividing by that geometry leaves a per-pair value proportional to speed (unknown scale).
Output rows: [frame_a, frame_a + 1, value, ground_points] for every VO step.
"""

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from pipeline.progress import report
from pipeline.vo import normalize


def ground_mask(width: int, height: int, static: np.ndarray | None = None) -> np.ndarray:
    """Lower-central part of the frame where the road usually is, minus camera-fixed overlays."""
    m = np.zeros((height, width), np.uint8)
    m[int(0.55 * height) :, int(0.15 * width) : int(0.85 * width)] = 255
    return m if static is None else cv2.bitwise_and(m, static)


def ground_speed(
    path: str, vo: np.ndarray, f: float, k1: float, mask: np.ndarray, win: int = 25, fb_max: float = 0.5
) -> np.ndarray:
    stride = int(vo[0, 1] - vo[0, 0])
    rot = {int(r[0]): r[4:7] for r in vo if np.isfinite(r[4:7]).all()}
    good = np.isfinite(vo[:, 7]) & (vo[:, 3] > 2) & (vo[:, 2] >= 30)
    if not good.any():
        raise ValueError("vizuální odometrie nenašla žádný pohyb vpřed")
    fwd = np.median(vo[good, 7:10], axis=0)
    foe = fwd[:2] / fwd[2]  # focus of expansion in normalised coords (camera fixed to the bike)

    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    c = np.array([w / 2, h / 2])
    lk = dict(winSize=(win, win), maxLevel=5, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    rows, prev = [], None
    for i in range(n):
        if not cap.grab():
            break
        # ground flow over a full VO step is ~30 px of blurred asphalt -> track over ONE frame right after each VO frame
        if i % stride not in (0, 1):
            continue
        report("rychlost z obrazu", i, n)
        _, frame = cap.retrieve()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if i % stride == 1 and prev is not None:
            i0 = i - 1
            val, npts = np.nan, 0
            p0 = cv2.goodFeaturesToTrack(prev, maxCorners=600, qualityLevel=0.003, minDistance=6, mask=mask)
            if p0 is not None and i0 in rot:
                p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, p0, None, **lk)
                pb, stb, _ = cv2.calcOpticalFlowPyrLK(gray, prev, p1, None, **lk)
                ok = (st[:, 0] == 1) & (stb[:, 0] == 1) & (np.linalg.norm(p0 - pb, axis=2)[:, 0] < fb_max)
                if ok.sum() >= 20:
                    a, b = normalize(p0[ok, 0], c, f, k1), normalize(p1[ok, 0], c, f, k1)
                    R = Rotation.from_rotvec(rot[i0] / stride).as_matrix()  # one frame of the VO step's rotation
                    ar = (R @ np.c_[a, np.ones(len(a))].T).T
                    ar = ar[:, :2] / ar[:, 2:]
                    trans = b - ar  # flow left after removing the camera rotation
                    rel = a - foe
                    below = rel[:, 1] > 0.05  # only points clearly below the horizon are ground
                    geom = np.linalg.norm(rel, axis=1) * rel[:, 1]
                    if below.sum() >= 15:
                        val = np.median(np.linalg.norm(trans[below], axis=1) / geom[below])
                        npts = int(below.sum())
            rows.append([i0, i, val, npts])
        if i % stride == 0:
            prev = gray
    cap.release()
    return np.array(rows, float).reshape(-1, 4)
