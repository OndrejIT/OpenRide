"""Read grade / speed / distance from the Garmin overlay (reference data for validation)."""

import re
import sys

import cv2
import numpy as np
from rapidocr import RapidOCR

from progress import Progress

video, out = sys.argv[1], sys.argv[2]
REGIONS = dict(grade=(1150, 665, 1250, 712), speed=(70, 605, 180, 660), dist=(95, 680, 180, 716))
PATTERNS = dict(grade=r"^(-?\d+)%$", speed=r"^(\d+)$", dist=r"^(\d+(?:\.\d)?)km$")

eng = RapidOCR()
cap = cv2.VideoCapture(video)
vfps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

rows = []
next_i = 0.0
prog = Progress("ocr", n / vfps)
for i in range(n):
    if not cap.grab():
        break
    if i < next_i:
        continue
    next_i += vfps
    _, frame = cap.retrieve()
    row = [i / vfps]
    for key, (x0, y0, x1, y1) in REGIONS.items():
        crop = cv2.resize(frame[y0:y1, x0:x1], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        val = np.nan
        for txt in eng(crop).txts or ():
            if m := re.match(PATTERNS[key], txt.replace(" ", "")):
                val = float(m.group(1))
                break
        row.append(val)
    rows.append(row)
    prog.update(i / vfps)

np.savetxt(out, np.array(rows), delimiter=",", header="t,grade,speed,dist", comments="", fmt="%.3f")
prog.update(n / vfps, force=True)
print("done", len(rows), "missing", np.isnan(np.array(rows)[:, 1:]).sum(0))
