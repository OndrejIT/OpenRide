"""Compare video-derived grade against Garmin overlay reference."""

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--grade", default="data/grade.csv")
ap.add_argument("--ref", default="data/reference.csv")
ap.add_argument("--gravity", default="data/gravity.npy")
ap.add_argument("--plot", default="data/compare.png")
ap.add_argument("--table", type=int, default=30, help="s step of printed table, 0 = off")
args = ap.parse_args()

g = np.genfromtxt(args.grade, delimiter=",", names=True)
r = np.genfromtxt(args.ref, delimiter=",", names=True)
t_max = np.load(args.gravity)[-1, 1]  # only seconds covered by GeoCalib

T = int(min(g["t"].max(), r["t"].max(), t_max)) + 1
video = np.interp(np.arange(T), g["t"], g["grade"], left=np.nan, right=np.nan)
video[np.isnan(np.interp(np.arange(T), g["t"], g["grade"]))] = np.nan
ref = np.full(T, np.nan)
ri = r["t"].round().astype(int)
m = ri < T
ref[ri[m]] = r["grade"][m]


def metrics(v, ref, lag=0):
    a, b = (v[lag:], ref[: len(ref) - lag]) if lag >= 0 else (v[:lag], ref[-lag:])
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 10:
        return dict(n=ok.sum(), mae=np.nan, bias=np.nan, corr=np.nan)
    d = a[ok] - b[ok]
    return dict(n=int(ok.sum()), mae=np.mean(np.abs(d)), bias=np.mean(d), corr=np.corrcoef(a[ok], b[ok])[0, 1])


m0 = metrics(video, ref)
lags = range(-20, 21)
best = max(lags, key=lambda L: np.nan_to_num(metrics(video, ref, L)["corr"], nan=-9))
mb = metrics(video, ref, best)
print(f"covered {T} s, compared {m0['n']} s")
print(f"lag 0: MAE {m0['mae']:.2f} %, bias {m0['bias']:+.2f} %, corr {m0['corr']:.3f}")
print(f"best lag {best:+d} s (video later if +): MAE {mb['mae']:.2f} %, bias {mb['bias']:+.2f} %, corr {mb['corr']:.3f}")

if args.table:
    print("t[s]  video%  garmin%")
    for t in range(0, T, args.table):
        print(f"{t:5d}  {video[t]:6.1f}  {ref[t]:6.0f}")

fig, ax = plt.subplots(figsize=(14, 4.5))
ax.plot(np.arange(T), ref, label="Garmin overlay", color="#888", lw=1.5)
ax.plot(np.arange(T), video, label="video (GeoCalib + VO)", color="#d62", lw=1.5)
ax.axhline(0, color="k", lw=0.5)
ax.set_xlabel("čas videa [s]")
ax.set_ylabel("sklon [%]")
ax.set_title(f"MAE {m0['mae']:.2f} %, bias {m0['bias']:+.2f} %, r={m0['corr']:.2f}")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(args.plot, dpi=110)
