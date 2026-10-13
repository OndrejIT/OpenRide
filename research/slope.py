"""Combine VO (relative poses) and GeoCalib (per-frame gravity) into road grade over time."""

import argparse

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation

ap = argparse.ArgumentParser()
ap.add_argument("--vo", default="data/vo.npy")
ap.add_argument("--gravity", default="data/gravity.npy")
ap.add_argument("--f", type=float, default=690)  # focal used by vo.py
ap.add_argument("--fps", type=float, default=30000 / 1001)
ap.add_argument("--up-sigma", type=float, default=20.0, help="s, gravity averaging window")
ap.add_argument("--grade-sigma", type=float, default=5.0, help="s, grade smoothing")
ap.add_argument("--out", default="data/grade.csv")
args = ap.parse_args()

vo = np.load(args.vo)
grav = np.load(args.gravity)
stride = int(vo[0, 1] - vo[0, 0])

# chain rotations into a per-segment world frame; a failed pair (scene cut, no texture) starts a new segment
n = len(vo)
W = np.zeros((n, 3, 3))
seg = np.zeros(n, int)
R_cur, s = np.eye(3), 0
for k in range(n):
    rv, mv = vo[k, 4:7], vo[k, 7:10]
    cut = not np.isfinite(rv).all() or np.linalg.norm(rv) > 0.3
    if cut:
        R_cur, s = np.eye(3), s + 1
    W[k], seg[k] = R_cur, s
    # weak pair: assume no rotation rather than breaking the segment
    if not cut and vo[k, 2] >= 30:
        R_cur = R_cur @ Rotation.from_rotvec(rv).as_matrix().T
t_node = vo[:, 0] / args.fps

# GeoCalib up vectors -> re-expressed with the VO focal (keeps horizon pixel position), then into world frame
node = np.clip(np.round(grav[:, 0] / stride).astype(int), 0, n - 1)
up = grav[:, 2:5] * np.c_[grav[:, 5] / args.f, grav[:, 5] / args.f, np.ones(len(grav))]
up /= np.linalg.norm(up, axis=1, keepdims=True)
up_w = np.einsum("kij,kj->ki", W[node], up)
w_g = 1 / (grav[:, 7] ** 2 + grav[:, 8] ** 2 + 1e-6)

U = np.full((n, 3), np.nan)
for s in np.unique(seg):
    idx = np.where(seg == s)[0]
    gi = np.where(seg[node] == s)[0]
    if len(gi) < 3:
        continue
    d = t_node[idx, None] - grav[gi, 1][None, :]
    k = np.exp(-0.5 * (d / args.up_sigma) ** 2) * w_g[gi][None, :]
    u = k @ up_w[gi]
    norm = np.linalg.norm(u, axis=1, keepdims=True)
    U[idx] = np.where(norm > 1e-6, u / np.maximum(norm, 1e-12), np.nan)

moving = np.isfinite(vo[:, 7]) & (vo[:, 3] > 2) & (vo[:, 2] >= 30)  # flow > 2 px: camera is actually moving
# camera is rigidly mounted -> travel direction is fixed in camera frame; per-pair VO translation is biased by the road plane
fwd = np.median(vo[moving, 7:10], axis=0)
fwd /= np.linalg.norm(fwd)
move_w = W @ fwd
ang = np.arcsin(np.clip((move_w * U).sum(1), -1, 1))
ok = np.isfinite(ang) & moving

# robust per-second resampling, then smoothing
T = int(t_node[-1]) + 1
sec = np.full(T, np.nan)
for t in range(T):
    a = ang[ok & (t_node >= t) & (t_node < t + 1)]
    if len(a) >= 2:
        sec[t] = np.median(a)
valid = np.isfinite(sec)
num = gaussian_filter1d(np.where(valid, sec, 0), args.grade_sigma)
den = gaussian_filter1d(valid.astype(float), args.grade_sigma)
smooth = np.where(den > 0.2, num / np.maximum(den, 1e-9), np.nan)
grade = 100 * np.tan(smooth)

np.savetxt(args.out, np.c_[np.arange(T), grade], delimiter=",", header="t,grade", comments="", fmt="%.2f")
print(f"segments {seg.max() + 1}, valid seconds {valid.sum()}/{T}, mean grade {np.nanmean(grade):.2f} %")
