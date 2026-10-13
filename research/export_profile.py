"""Build web/tyrol.js (per-second grade, speed, distance, elevation) for the sync preview page."""

import json
import os

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEO_ID = "QEI8NBHlwSE"

ref = np.genfromtxt(f"{ROOT}/data/reference.csv", delimiter=",", names=True)
T = int(ref["t"].max()) + 1
t = np.arange(T)


def fill(col):
    # OCR gaps -> linear interpolation over time
    ok = np.isfinite(ref[col])
    return np.interp(t, ref["t"][ok], ref[col][ok])


# speed OCR occasionally misreads a digit -> short median filter
speed = median_filter(fill("speed"), 5)
dist = np.concatenate([[0], np.cumsum(speed[:-1] / 3.6)])
grade = gaussian_filter1d(fill("grade"), 3)
elev = np.concatenate([[0], np.cumsum(grade[:-1] / 100 * np.diff(dist))])

video = [None] * T
path = f"{ROOT}/data/grade_sfm.csv"
if os.path.exists(path):
    sfm = np.genfromtxt(path, delimiter=",", names=True)
    for ti, g in zip(sfm["t"].astype(int), sfm["grade"]):
        if 0 <= ti < T and np.isfinite(g):
            video[ti] = round(float(g), 1)

# video elevation: each contiguous SfM piece starts at the Garmin elevation and integrates the video grade;
# distance step comes from Garmin speed because monocular video has no metric scale
elev_video = [None] * T
for s in range(T):
    if video[s] is None:
        continue
    prev = elev_video[s - 1] if s > 0 else None
    elev_video[s] = round(float(elev[s] if prev is None else prev + video[s - 1] / 100 * (dist[s] - dist[s - 1])), 1)

data = dict(
    title="South Tyrol, Lake Tour", videoId=VIDEO_ID, refLabel="Garmin",
    grade=np.round(grade, 1).tolist(),
    speed=np.round(speed, 1).tolist(),
    dist=np.round(dist / 1000, 3).tolist(),
    elev=np.round(elev, 1).tolist(),
    gradeVideo=video,
    elevVideo=elev_video,
)
os.makedirs(f"{ROOT}/web", exist_ok=True)
with open(f"{ROOT}/web/tyrol.js", "w") as f:
    f.write("window.PROFILE = " + json.dumps(data, separators=(",", ":")) + ";\n")
print(f"{T} s, {dist[-1] / 1000:.2f} km, elev {elev.min():.0f}..{elev.max():.0f} m (end {elev[-1]:+.0f}), "
      f"video grade {sum(v is not None for v in video)} s")
