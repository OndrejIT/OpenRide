"""Does a longer smoothing window make SfM grade beat a constant? Gaussian smoothing of video (and Garmin) grade.

usage: sfm_smooth.py   (uses all SfM fragments in data/sfm, regions: flat 0-600 s, descent 1640-1760 s)
"""

import re
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

ROOT = Path(__file__).parent
# reuse helpers (models, poses, up_world, grade_series, metrics, garmin) without running sfm_summary's main part
sys.argv = [sys.argv[0], "0", "1", "unused.png"]
exec(open(ROOT / "sfm_summary.py").read().split("# per window start")[0])

import matplotlib.pyplot as plt  # noqa: E402

SIGMAS_V = (5, 10, 15, 20, 30)
REGIONS = {"rovina 0-600": (0, 600), "sjezd 1640": (1600, 1800)}


def gauss(x, sigma):
    """NaN-aware Gaussian smoothing (normalised convolution) on a 1 Hz series."""
    if sigma == 0:
        return x
    ok = np.isfinite(x)
    num = gaussian_filter1d(np.where(ok, x, 0.0), sigma, mode="constant")
    den = gaussian_filter1d(ok.astype(float), sigma, mode="constant")
    return np.where(den > 0.3, num / np.maximum(den, 1e-9), np.nan)


# one run per window start: the fps directory with the most registered images
runs = {}
for work in sorted((ROOT / "data" / "sfm").iterdir()):
    m = re.match(r"(\d+)_([\d.]+)fps$", work.name)
    if not m:
        continue
    recs = models(work)
    n = sum(r.num_reg_images() for r in recs)
    s0 = int(m.group(1))
    if recs and (s0 not in runs or n > runs[s0][0]):
        runs[s0] = (n, recs, float(m.group(2)))

# fragments: per-second raw video grade for variants a) and c) sigma=20
frags = []
for s0, (_, recs, fps) in sorted(runs.items()):
    for rec in recs:
        t, C, R_wc = poses(rec, s0, fps)
        cam = next(iter(rec.cameras.values()))
        U, _ = up_mean(t, R_wc, cam)
        tg, upw = up_world(t, R_wc, cam)
        secs, ga, _, _ = grade_series(t, C, U)
        _, gc, _, _ = grade_series(t, C, U, sigma=20, tg=tg, upw=upw)
        frags.append(dict(secs=secs, a=ga, c=gc))

# Garmin on a 1 Hz grid, gaps interpolated, so it can be smoothed like the video
grid = np.arange(0, int(rt[-1]) + 1)
g_raw = np.interp(grid, rt, rg)


def evaluate(region, var, sv, sg):
    lo_, hi_ = REGIONS[region]
    g_s = gauss(g_raw, sg) if sg else g_raw
    best = None
    for lag in range(-20, 21):
        V, G = [], []
        for f in frags:
            if not (lo_ <= f["secs"][0] < hi_):
                continue
            V.append(gauss(f[var], sv))
            G.append(np.interp(f["secs"] + lag, grid, g_s))
        V, G = np.concatenate(V), np.concatenate(G)
        m = metrics(V, G)
        ok = np.isfinite(V) & np.isfinite(G)
        m["const"] = np.mean(np.abs(np.median(G[ok]) - G[ok]))
        m["lag"] = lag
        if lag == 0:
            m0 = m
        if best is None or np.nan_to_num(m["r"], nan=-9) > np.nan_to_num(best["r"], nan=-9):
            best = m
    return m0, best


rows = []
print(f"{'oblast':<14}{'var':<5}{'σv':>4}{'σG':>5} | {'lag0: r':>8}{'MAE':>6}{'const':>6} | {'lag*':>5}{'r':>6}{'gain':>6}{'bias':>6}{'MAE':>6}{'const':>6}")
for region in REGIONS:
    for var in ("a", "c"):
        for sv in SIGMAS_V:
            for sg in (0, sv):
                m0, mb = evaluate(region, var, sv, sg)
                rows.append((region, var, sv, sg, m0, mb))
                print(f"{region:<14}{var:<5}{sv:>4}{sg:>5} | {m0['r']:>8.2f}{m0['mae']:>6.2f}{m0['const']:>6.2f} | "
                      f"{mb['lag']:>+5d}{mb['r']:>6.2f}{mb['gain']:>6.2f}{mb['bias']:>+6.2f}{mb['mae']:>6.2f}{mb['const']:>6.2f}")

# plot: per region, the combination with lowest MAE-minus-constant at lag 0 (no lag fitting: what a trainer would get)
fig, axes = plt.subplots(2, 1, figsize=(14, 7))
for ax, region in zip(axes, REGIONS):
    cand = [r for r in rows if r[0] == region]
    region_, var, sv, sg, m0, mb = min(cand, key=lambda r: r[4]["mae"] - r[4]["const"])
    lo_, hi_ = REGIONS[region]
    ax.plot(grid, g_raw, color="gray", lw=0.8, label="Garmin")
    if sg:
        ax.plot(grid, gauss(g_raw, sg), color="k", lw=1, label=f"Garmin σ={sg}s")
    first = True
    for f in frags:
        if lo_ <= f["secs"][0] < hi_:
            ax.plot(f["secs"], gauss(f[var], sv), color="C1", lw=1.5, label=f"video {var}) σ={sv}s" if first else None)
            first = False
    ax.set_xlim(max(lo_, min(f["secs"][0] for f in frags if lo_ <= f["secs"][0] < hi_)),
                min(hi_, max(f["secs"][-1] for f in frags if lo_ <= f["secs"][0] < hi_)))
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title(f"{region}: lag0 MAE {m0['mae']:.2f} % vs konstanta {m0['const']:.2f} %")
    ax.set_ylabel("sklon [%]")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left")
axes[-1].set_xlabel("čas videa [s]")
fig.tight_layout()
fig.savefig(ROOT / "data" / "sfm_smooth.png", dpi=110)
