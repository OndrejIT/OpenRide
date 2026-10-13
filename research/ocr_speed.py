"""OCR speed from the on-screen overlay (Deer Creek video): km/h, falling back to mph."""

import sys

import cv2
import numpy as np
from rapidocr import RapidOCR

from progress import Progress

video, out = sys.argv[1], sys.argv[2]
rate = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
KMH, MPH = (1135, 300, 1215, 350), (1135, 175, 1215, 225)  # x0, y0, x1, y1 at 1280x720

eng = RapidOCR()
cap = cv2.VideoCapture(video)
vfps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
prog = Progress("ocr_speed", n / vfps)


def read(frame, box):
    x0, y0, x1, y1 = box
    crop = cv2.resize(frame[y0:y1, x0:x1], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    for txt in eng(crop).txts or ():
        if txt.isdigit():
            return float(txt)
    return np.nan


rows, next_i = [], 0.0
for i in range(n):
    if not cap.grab():
        break
    if i < next_i:
        continue
    next_i += vfps / rate
    _, frame = cap.retrieve()
    rows.append([i / vfps, read(frame, KMH), read(frame, MPH)])
    prog.update(i / vfps)

np.savetxt(out, np.array(rows), delimiter=",", header="t,kmh,mph", comments="", fmt="%.3f")
prog.update(n / vfps, force=True)
print("done", len(rows), "missing kmh/mph", np.isnan(np.array(rows)[:, 1:]).sum(0))
