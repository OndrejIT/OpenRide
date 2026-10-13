"""Compare GPX alignment without OCR (flow) against the OCR-speed alignment and the Garmin overlay."""

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

D = sys.argv[1] if len(sys.argv) > 1 else "data/tyrol_gpx"
fl, oc = np.load(f"{D}/align_flow.npz"), np.load(f"{D}/align_csv.npz")
ref = np.genfromtxt("data/reference.csv", delimiter=",", names=True)
t = oc["t"]
n = min(len(t), len(fl["t"]))
t = t[:n]

ok = np.isfinite(ref["grade"])
garmin = np.interp(t, ref["t"][ok], ref["grade"][ok])
ok = np.isfinite(ref["speed"])
v_ocr = np.maximum(np.interp(t, ref["t"][ok], ref["speed"][ok]) / 3.6, 1.0)

err = fl["d"][:n] - oc["d"][:n]
err_s = err / v_ocr
rows = [
    ("start v GPX [km]", f"{fl['s0'] / 1000:.3f}", f"{oc['s0'] / 1000:.3f}"),
    ("průměrná rychlost [km/h]", f"{fl['speed'][:n].mean():.1f}", f"{oc['speed'][:n].mean():.1f}"),
    ("délka úseku [km]", f"{(fl['d'][n - 1] - fl['s0']) / 1000:.2f}", f"{(oc['d'][n - 1] - oc['s0']) / 1000:.2f}"),
    ("korelace zatáček", f"{float(fl['score']):.2f}", f"{float(oc['score']):.2f}"),
    ("převýšení (konec−start) [m]", f"{fl['ele'][n - 1] - fl['ele'][0]:.0f}", f"{oc['ele'][n - 1] - oc['ele'][0]:.0f}"),
]
for name, key in [("sklon GPX vs Garmin: r", "r"), ("sklon GPX vs Garmin: MAE [%]", "mae")]:
    vals = []
    for a in (fl, oc):
        gg = a["grade"][:n]
        vals.append(f"{np.corrcoef(gg, garmin)[0, 1]:.2f}" if key == "r" else f"{np.mean(np.abs(gg - garmin)):.2f}")
    rows.append((name, *vals))
print(f"{'':32s} {'bez OCR':>10s} {'s OCR':>10s}")
for r in rows:
    print(f"{r[0]:32s} {r[1]:>10s} {r[2]:>10s}")
print(f"\npoloha bez OCR − s OCR: medián {np.median(np.abs(err)):.0f} m, 90% {np.percentile(np.abs(err), 90):.0f} m, max {np.abs(err).max():.0f} m")
print(f"                        medián {np.median(np.abs(err_s)):.1f} s, 90% {np.percentile(np.abs(err_s), 90):.1f} s, max {np.abs(err_s).max():.1f} s")
print(f"sklon GPX bez OCR vs s OCR: MAE {np.mean(np.abs(fl['grade'][:n] - oc['grade'][:n])):.2f} %, r {np.corrcoef(fl['grade'][:n], oc['grade'][:n])[0, 1]:.2f}")

fig, ax = plt.subplots(3, 1, figsize=(15, 9), sharex=True)
ax[0].plot(t, err, color="#eb6834")
ax[0].set_ylabel("poloha bez OCR − s OCR [m]")
ax[1].plot(t, fl["speed"][:n], label="rychlost z obrazu (flow, přeškálovaná)", color="#eb6834")
ax[1].plot(t, oc["speed"][:n], label="rychlost OCR", color="#52514e")
ax[1].set_ylabel("km/h")
ax[1].legend()
ax[2].plot(t, garmin, label="Garmin overlay", color="#8a8984")
ax[2].plot(t, oc["grade"][:n], label="GPX – napárováno s OCR", color="#52514e")
ax[2].plot(t, fl["grade"][:n], label="GPX – napárováno bez OCR", color="#eb6834")
ax[2].set_ylabel("sklon [%]")
ax[2].set_xlabel("čas videa [s]")
ax[2].legend()
for a in ax:
    a.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f"{D}/compare_align.png", dpi=80)
print(f"graf {D}/compare_align.png")
