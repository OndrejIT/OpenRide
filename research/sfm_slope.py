"""Road grade from SfM trajectory (pycolmap) + GeoCalib gravity, validated against the Garmin overlay.

usage: sfm_slope.py <start_s> <dur_s> <fps> <camera_model> <step...>
steps: extract features match map analyze (or "all")
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from progress import Progress

ROOT = Path(__file__).parent
VIDEO = ROOT / "data" / "tyrol.mp4"
VFPS = 30000 / 1001

start, dur, fps, model = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
steps = sys.argv[5:] or ["all"]
if steps == ["all"]:
    steps = ["extract", "features", "match", "map", "analyze"]
work = ROOT / "data" / "sfm" / f"{int(start)}_{fps:g}fps"
images = work / "images"
db = work / f"{model}.db"
recon = work / f"rec_{model}"
INIT = {"OPENCV_FISHEYE": "620,620,640,360,0,0,0,0", "RADIAL": "700,640,360,0,0"}
# initial intrinsics override, e.g. from a previous partial reconstruction (bad init breaks two-view verification)
INIT[model] = os.environ.get("CAM_PARAMS", INIT[model])


def frame_time(name: str) -> float:
    return start + (int(Path(name).stem) - 1) / fps


def step_extract():
    images.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(VIDEO), "-t", str(dur),
                    "-vf", f"fps={fps}", "-q:v", "2", str(images / "%05d.jpg")], check=True)
    print("frames", len(list(images.glob("*.jpg"))))


def step_features():
    import pycolmap
    db.unlink(missing_ok=True)
    reader = pycolmap.ImageReaderOptions(camera_model=model, camera_params=INIT[model])
    ext = pycolmap.FeatureExtractionOptions()
    ext.sift.max_num_features = 4000
    pycolmap.extract_features(db, images, camera_mode=pycolmap.CameraMode.SINGLE, reader_options=reader,
                              extraction_options=ext, device=pycolmap.Device.cpu)


def step_match():
    import pycolmap
    pair = pycolmap.SequentialPairingOptions(overlap=20, loop_detection=False)
    pycolmap.match_sequential(db, pairing_options=pair, device=pycolmap.Device.cpu)


def step_map():
    import pycolmap
    n = len(list(images.glob("*.jpg")))
    prog = Progress(f"sfm_map_{model}", n)
    count = [0]

    def on_image():
        count[0] += 1
        prog.update(count[0])

    opts = pycolmap.IncrementalPipelineOptions()
    opts.ba_refine_focal_length = True
    opts.ba_refine_extra_params = True
    # forward motion through foliage gives few inliers; default thresholds fragment the model
    opts.mapper.init_min_num_inliers = 50
    opts.mapper.abs_pose_min_num_inliers = 15
    opts.min_model_size = 20
    opts.mapper.init_max_forward_motion = 0.99
    recon.mkdir(parents=True, exist_ok=True)
    recs = pycolmap.incremental_mapping(db, images, recon, opts, next_image_callback=on_image)
    prog.update(n, force=True)
    for k, r in recs.items():
        cam = next(iter(r.cameras.values()))
        print(f"model {k}: {r.num_reg_images()}/{n} images, {r.num_points3D()} pts, "
              f"reproj {r.compute_mean_reprojection_error():.3f}px, cam {cam.model.name} {np.round(cam.params, 4).tolist()}")


def load_poses():
    import pycolmap
    best = max((pycolmap.Reconstruction(p) for p in recon.iterdir() if p.is_dir()), key=lambda r: r.num_reg_images())
    cam = next(iter(best.cameras.values()))
    rows = []
    for img in best.images.values():
        cfw = img.cam_from_world() if callable(img.cam_from_world) else img.cam_from_world
        R_cw = cfw.rotation.matrix()
        C = -R_cw.T @ cfw.translation  # camera centre in world
        rows.append((frame_time(img.name), C, R_cw.T))
    rows.sort(key=lambda r: r[0])
    t = np.array([r[0] for r in rows])
    C = np.array([r[1] for r in rows])
    R_wc = np.array([r[2] for r in rows])
    return t, C, R_wc, cam


def grade_series(t, C, U, win):
    """Grade per second: dh/ds by linear fit over +-win/2 s (robust to per-frame jitter)."""
    h = C @ U
    horiz = C - np.outer(h, U)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(horiz, axis=0), axis=1))]
    secs = np.arange(np.ceil(t[0]), np.floor(t[-1]) + 1)
    out = np.full(len(secs), np.nan)
    for i, ts in enumerate(secs):
        m = np.abs(t - ts) <= win / 2
        if m.sum() >= 4 and np.ptp(s[m]) > 0:
            out[i] = 100 * np.polyfit(s[m], h[m], 1)[0]
    return secs, out, h, s


def metrics(v, g):
    m = np.isfinite(v) & np.isfinite(g)
    v, g = v[m], g[m]
    gain = np.polyfit(g, v, 1)[0] if np.ptp(g) > 0 else np.nan
    r = np.corrcoef(v, g)[0, 1] if np.std(v) > 0 else np.nan
    return dict(n=m.sum(), r=r, gain=gain, bias=np.mean(v - g), mae=np.mean(np.abs(v - g)))


def step_analyze():
    t, C, R_wc, cam = load_poses()
    f_col = cam.params[0]
    grav = np.load(ROOT / "data" / "gravity.npy")
    gm = (grav[:, 1] >= t[0]) & (grav[:, 1] <= t[-1])
    grav = grav[gm]
    # GeoCalib up re-expressed with COLMAP focal (keeps horizon pixel position)
    up = grav[:, 2:5] * np.c_[grav[:, 5] / f_col, grav[:, 5] / f_col, np.ones(len(grav))]
    up /= np.linalg.norm(up, axis=1, keepdims=True)
    # nearest registered frame for each gravity sample
    idx = np.abs(t[None, :] - grav[:, 1][:, None]).argmin(1)
    close = np.abs(t[idx] - grav[:, 1]) < 0.2
    up, idx = up[close], idx[close]
    Rk = R_wc[idx]
    w = 1 / (grav[close, 7] ** 2 + grav[close, 8] ** 2 + 1e-6)

    # a) robust weighted mean of world-frame up (iteratively drop >3 MAD outliers)
    up_w = np.einsum("kij,kj->ki", Rk, up)
    keep = np.ones(len(up_w), bool)
    for _ in range(3):
        Ua = (w[keep, None] * up_w[keep]).sum(0)
        Ua /= np.linalg.norm(Ua)
        ang = np.degrees(np.arccos(np.clip(up_w @ Ua, -1, 1)))
        keep = ang < np.median(ang) + 3 * 1.4826 * np.median(np.abs(ang - np.median(ang)))

    # b) GeoCalib up pulled towards a camera-fixed direction (road normal): up_cam = R^T c + b
    A = np.zeros((3 * len(up), 6))
    A[:, :3] = np.transpose(Rk, (0, 2, 1)).reshape(-1, 3)
    A[:, 3:] = np.tile(np.eye(3), (len(up), 1))
    sw = np.repeat(np.sqrt(w / w.mean()), 3)
    x, *_ = np.linalg.lstsq(A * sw[:, None], up.reshape(-1) * sw, rcond=None)
    Ub = x[:3] / np.linalg.norm(x[:3])
    # sign: up should point roughly opposite to camera y (image down)
    if (R_wc[:, :, 1] @ Ub).mean() > 0:
        Ub = -Ub

    ref = np.genfromtxt(ROOT / "data" / "reference.csv", delimiter=",", names=True)
    rm = np.isfinite(ref["grade"])
    out = {}
    for name, U in [("a", Ua), ("b", Ub)]:
        for win in (5, 10):
            secs, gr, h, s = grade_series(t, C, U, win)
            g = np.interp(secs, ref["t"][rm], ref["grade"][rm])
            lags = {lag: metrics(gr, np.interp(secs + lag, ref["t"][rm], ref["grade"][rm]))["r"] for lag in range(-15, 16)}
            best = max(lags, key=lambda k: -np.inf if np.isnan(lags[k]) else lags[k])
            out[(name, win)] = (secs, gr, metrics(gr, g), best)
    secs = out[("a", 10)][0]
    g = np.interp(secs, ref["t"][rm], ref["grade"][rm])
    base = np.full_like(g, np.median(g))

    print(f"gravity samples {close.sum()}, kept a) {keep.sum()}, angle a-b {np.degrees(np.arccos(np.clip(Ua @ Ub, -1, 1))):.2f} deg")
    print(f"{'variant':<12}{'n':>4}{'r':>7}{'gain':>7}{'bias':>7}{'MAE':>7}{'lag':>5}")
    for (name, win), (_, gr, m, lag) in out.items():
        print(f"{name} win{win:<6}{m['n']:>4}{m['r']:>7.2f}{m['gain']:>7.2f}{m['bias']:>7.2f}{m['mae']:>7.2f}{lag:>5}")
    mb = metrics(base, g)
    print(f"{'baseline':<12}{mb['n']:>4}{'-':>7}{'-':>7}{mb['bias']:>7.2f}{mb['mae']:>7.2f}")

    # consistency: total drop, video (scale from Garmin distance travelled) vs Garmin integral
    sp = np.interp(secs, ref["t"][np.isfinite(ref["speed"])], ref["speed"][np.isfinite(ref["speed"])]) / 3.6
    drop_garmin = np.sum(g / 100 * sp)
    for name, U in [("a", Ua), ("b", Ub)]:
        _, _, h, s = grade_series(t, C, U, 10)
        scale = np.sum(sp) / s[-1]
        print(f"drop {name}: video {scale * (h[-1] - h[0]):.1f} m vs Garmin {drop_garmin:.1f} m (path {np.sum(sp):.0f} m)")

    print("t      a10    b10  garmin")
    ga, gb = out[("a", 10)][1], out[("b", 10)][1]
    for i in range(0, len(secs), 10):
        print(f"{secs[i]:.0f}  {ga[i]:6.1f} {gb[i]:6.1f} {g[i]:6.0f}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(ref["t"], ref["grade"], color="gray", label="Garmin overlay")
    ax.plot(secs, ga, label="SfM + gravity a) mean")
    ax.plot(secs, gb, label="SfM + gravity b) road-normal model")
    ax.set_xlim(secs[0], secs[-1])
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("video time [s]")
    ax.set_ylabel("grade [%]")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(ROOT / "data" / "sfm_compare.png", dpi=110)


for st in steps:
    t0 = time.time()
    globals()[f"step_{st}"]()
    print(f"[{st}] {time.time() - t0:.0f}s", flush=True)
