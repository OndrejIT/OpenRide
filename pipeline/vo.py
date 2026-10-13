"""Visual odometry: frame-to-frame relative pose (rotation + translation direction) via KLT + essential matrix.

Output rows (one per VO step): [frame_a, frame_b, inliers, median_flow_px, rotvec(3), move(3)];
`move` is the camera centre of frame b expressed in frame a (unit length), NaN when the step failed.
"""

import logging

import cv2
import numpy as np

from pipeline.progress import report

log = logging.getLogger(__name__)

LK = dict(winSize=(21, 21), maxLevel=4, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))


def video_info(path: str) -> tuple[float, int, int, int]:
    """(fps, frame count, width, height)."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"nelze otevřít video {path}")
    info = (
        cap.get(cv2.CAP_PROP_FPS),
        int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    cap.release()
    return info


def normalize(px: np.ndarray, c: np.ndarray, f: float, k1: float) -> np.ndarray:
    """Pixel -> undistorted normalized coords (GeoCalib simple_divisional model)."""
    p = (px - c) / f
    return p / (1 + k1 * (p**2).sum(1, keepdims=True))


def static_mask(path: str, samples: int = 80, grad_thr: float = 40.0, grow: int = 41) -> np.ndarray:
    """Mask (255 = track) hiding overlays burnt into the video.

    Moving scenery blurs out in the mean of frames spread over the video; only camera-fixed graphics keep sharp edges.
    """
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    acc, cnt = None, 0
    for k, i in enumerate(np.linspace(0, max(n - 1, 0), samples).astype(int)):
        report("maska overlaye", k, samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, frame = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        acc = g if acc is None else acc + g
        cnt += 1
    cap.release()
    if acc is None:
        raise ValueError(f"nelze číst snímky z {path}")
    mean = acc / cnt
    grad = np.hypot(cv2.Sobel(mean, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(mean, cv2.CV_32F, 0, 1, ksize=3))
    static = cv2.dilate((grad > grad_thr).astype(np.uint8), np.ones((grow, grow), np.uint8))
    return np.where(static > 0, 0, 255).astype(np.uint8)


def relative_poses(path: str, f: float, k1: float, stride: int, mask: np.ndarray | None = None) -> np.ndarray:
    """Relative pose for frame pairs `stride` apart over the whole video."""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    c = np.array([w / 2, h / 2])
    rows, prev = [], None
    for i in range(n):
        if not cap.grab():
            break
        if i % stride:
            continue
        _, frame = cap.retrieve()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            rows.append(_pose(prev, gray, i, stride, c, f, k1, mask))
            report("vizuální odometrie", i, n)
            if len(rows) % 1000 == 0:
                log.info("vo %d/%d frames", i, n)
        prev = gray
    cap.release()
    return np.array(rows, float).reshape(-1, 10)


def _pose(prev, gray, i, stride, c, f, k1, mask) -> list:
    row = [i - stride, i, 0, np.nan, *[np.nan] * 6]
    p0 = cv2.goodFeaturesToTrack(prev, maxCorners=2000, qualityLevel=0.005, minDistance=8, mask=mask)
    if p0 is None or len(p0) < 50:
        return row
    p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, p0, None, **LK)
    pb, stb, _ = cv2.calcOpticalFlowPyrLK(gray, prev, p1, None, **LK)
    ok = (st[:, 0] == 1) & (stb[:, 0] == 1) & (np.linalg.norm(p0 - pb, axis=2)[:, 0] < 0.5)
    a, b = p0[ok, 0], p1[ok, 0]
    if len(a) < 50:
        return row
    flow = np.median(np.linalg.norm(b - a, axis=1))
    na, nb = normalize(a, c, f, k1), normalize(b, c, f, k1)
    E, emask = cv2.findEssentialMat(na, nb, np.eye(3), cv2.RANSAC, 0.999, 1.0 / f)
    if E is None or E.shape != (3, 3):
        return row
    inl, R, t, _ = cv2.recoverPose(E, na, nb, np.eye(3), mask=emask)
    move = (-R.T @ t).ravel()
    return [i - stride, i, inl, flow, *cv2.Rodrigues(R)[0].ravel(), *move]
