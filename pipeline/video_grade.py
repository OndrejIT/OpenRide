"""Road grade from the video alone: GeoCalib gravity + SfM (pycolmap) trajectory fragments.

Best effort and slow (hours for a long video). The SfM trajectory has no metric scale, but grade is a ratio,
so only the up direction matters; it comes from GeoCalib, re-expressed in COLMAP's camera through two horizon points
(the two lens models disagree strongly on a fisheye's field of view, a focal-ratio rescale is wrong).
GeoCalib intrinsics are also used for VO in the GPX pipeline.
"""

import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from pipeline.gpx import build_profile
from pipeline.progress import report

log = logging.getLogger(__name__)

# (COLMAP camera model, fps) tried per window until registration is good: action-cam fisheye (Tyrol) first,
# then a radial lens at a higher rate for fast rides (Deer Creek: fisheye at 6 fps registers 2/150 frames)
SFM_ATTEMPTS = (("OPENCV_FISHEYE", 6.0), ("RADIAL", 12.0))
MIN_IMAGES = 100
SFM_WINDOW_S = 150.0
SFM_OVERLAP_S = 15.0
GRADE_SIGMA_S = 15.0


def _geocalib():
    import torch
    from geocalib import GeoCalib

    torch.set_grad_enabled(False)
    return GeoCalib(weights="distorted")


def _calibrate(model, frame):
    import cv2
    import torch

    img = torch.from_numpy(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float() / 255
    return model.calibrate(img, camera_model="simple_divisional")


def estimate_intrinsics(path: str, samples: int = 15) -> tuple[float, float]:
    """Median GeoCalib focal length [px] and k1 (simple_divisional) over frames spread across the video."""
    import cv2

    model = _geocalib()
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fs, ks = [], []
    for k, i in enumerate(np.linspace(0.05 * n, 0.95 * n, samples).astype(int)):
        report("parametry kamery (GeoCalib)", k, samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, frame = cap.read()
        if not ok:
            continue
        cam = _calibrate(model, frame)["camera"]
        fs.append(cam.f[0, 0].item())
        ks.append(cam.k1[0].item())
    cap.release()
    if not fs:
        raise ValueError(f"nelze číst snímky z {path}")
    return float(np.median(fs)), float(np.median(ks))


def gravity(path: str, fps: float = 1.0) -> np.ndarray:
    """Per-frame up vector (camera frame) and intrinsics: [frame, t, up(3), f, k1, roll/pitch/focal uncertainty]."""
    import cv2
    import torch

    model = _geocalib()
    cap = cv2.VideoCapture(str(path))
    vfps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step, next_i, rows = vfps / fps, 0.0, []
    for i in range(n):
        if not cap.grab():
            break
        if i < next_i:
            continue
        next_i += step
        report("směr gravitace (GeoCalib)", i, n)
        _, frame = cap.retrieve()
        r = _calibrate(model, frame)
        cam, g = r["camera"], r["gravity"]
        unc = [
            r.get(k, torch.zeros(1)).flatten()[0].item()
            for k in ("roll_uncertainty", "pitch_uncertainty", "focal_uncertainty")
        ]
        rows.append([i, i / vfps, *g.vec3d[0].tolist(), cam.f[0, 0].item(), cam.k1[0].item(), *unc])
    cap.release()
    return np.array(rows, float).reshape(-1, 10)


def windows(start: float, end: float, win: float, overlap: float) -> list[tuple[float, float]]:
    out, s = [], start
    while s < end:
        e = min(s + win, end)
        out.append((max(start, e - win), e))  # keep last window full length
        if e >= end:
            break
        s = e - overlap
    return out


def sfm_window(
    video: Path, work: Path, start: float, dur: float, fps: float, mask: Path | None, f: float, model: str
) -> list:
    """Reconstruct one window; returns (reconstruction, registered ratio) pairs (a window can fragment)."""
    import pycolmap

    images, db, recon = work / "images", work / "features.db", work / "rec"
    shutil.rmtree(work, ignore_errors=True)
    images.mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(video), "-t", str(dur),
         "-vf", f"fps={fps}", "-q:v", "2", str(images / "%05d.jpg")],
        check=True,
    )  # fmt: skip
    n = len(list(images.glob("*.jpg")))
    w, h = _image_size(next(images.glob("*.jpg")))
    init = {"OPENCV_FISHEYE": f"{f},{f},{w / 2},{h / 2},0,0,0,0", "RADIAL": f"{f},{w / 2},{h / 2},0,0"}[model]
    reader = pycolmap.ImageReaderOptions(camera_model=model, camera_params=init)
    if mask is not None:
        reader.camera_mask_path = str(mask)  # black = no features (camera-fixed overlay would pin the motion)
    ext = pycolmap.FeatureExtractionOptions()
    ext.sift.max_num_features = 4000
    pycolmap.extract_features(
        db, images, camera_mode=pycolmap.CameraMode.SINGLE, reader_options=reader,
        extraction_options=ext, device=pycolmap.Device.cpu,
    )  # fmt: skip
    pair = pycolmap.SequentialPairingOptions(overlap=20, loop_detection=False)
    pycolmap.match_sequential(db, pairing_options=pair, device=pycolmap.Device.cpu)
    opts = pycolmap.IncrementalPipelineOptions()
    opts.ba_refine_focal_length = True
    opts.ba_refine_extra_params = True
    # forward motion with few inliers; default thresholds fragment the model
    opts.mapper.init_min_num_inliers = 50
    opts.mapper.abs_pose_min_num_inliers = 15
    opts.min_model_size = 20
    opts.mapper.init_max_forward_motion = 0.99
    recon.mkdir(parents=True, exist_ok=True)
    recs = list(pycolmap.incremental_mapping(db, images, recon, opts).values())
    reg = sum(r.num_reg_images() for r in recs)
    log.info("sfm %s: %d/%d images registered in %d fragments", work.name, reg, n, len(recs))
    # frames and the feature DB are big and fully reproducible; the reconstructions are small
    shutil.rmtree(images)
    db.unlink(missing_ok=True)
    return [(r, reg / max(n, 1)) for r in recs]


def _image_size(p: Path) -> tuple[int, int]:
    import cv2

    h, w = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE).shape
    return w, h


def geocalib_project(d, f, k1, c):
    """Direction -> pixel with GeoCalib's simple_divisional camera."""
    p = d[:, :2] / d[:, 2:3]
    r2 = (p**2).sum(1, keepdims=True)
    k = k1[:, None]
    radial = np.where(
        np.abs(k * r2) < 1e-9, 1.0, (1 - np.sqrt(np.clip(1 - 4 * k * r2, 0, None))) / (2 * k * r2 + 1e-12)
    )
    return f[:, None] * p * radial + np.array(c)


def reproject_up(g, cam):
    """GeoCalib up -> COLMAP camera via two horizon points (~±29° azimuth, well inside the image)."""
    c = (cam.width / 2, cam.height / 2)
    up = g[:, 2:5] / np.linalg.norm(g[:, 2:5], axis=1, keepdims=True)
    fwd = np.array([0.0, 0.0, 1.0]) - up[:, 2:3] * up
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True)
    side = np.cross(up, fwd)
    rays = []
    for a in (-0.5, 0.5):
        px = geocalib_project(np.cos(a) * fwd + np.sin(a) * side, g[:, 5], g[:, 6], c)
        xy = cam.cam_from_img(px)
        rays.append(np.c_[xy, np.ones(len(xy))])
    new = np.cross(rays[1], rays[0])
    new /= np.linalg.norm(new, axis=1, keepdims=True)
    return np.where((new * up).sum(1, keepdims=True) < 0, -new, new)


def poses(rec, start: float, fps: float):
    rows = []
    for img in rec.images.values():
        cfw = img.cam_from_world() if callable(img.cam_from_world) else img.cam_from_world
        R_cw = cfw.rotation.matrix()
        rows.append((start + (int(Path(img.name).stem) - 1) / fps, -R_cw.T @ cfw.translation, R_cw.T))
    rows.sort(key=lambda r: r[0])
    return np.array([r[0] for r in rows]), np.array([r[1] for r in rows]), np.array([r[2] for r in rows])


def fragment_grade(rec, start: float, fps: float, grav: np.ndarray, win: float = 10):
    """Per-second grade [%] of one SfM fragment: dh/ds by linear fit over ±win/2 s, up = mean GeoCalib up."""
    t, C, R_wc = poses(rec, start, fps)
    cam = next(iter(rec.cameras.values()))
    g = grav[(grav[:, 1] >= t[0]) & (grav[:, 1] <= t[-1])]
    if not len(g):
        return None
    idx = np.abs(t[None, :] - g[:, 1][:, None]).argmin(1)
    ok = np.abs(t[idx] - g[:, 1]) < 0.2
    if ok.sum() < 3:
        return None
    upw = np.einsum("kij,kj->ki", R_wc[idx[ok]], reproject_up(g[ok], cam))
    U = upw.mean(0)
    U /= np.linalg.norm(U)
    h = C @ U
    horiz = C - np.outer(h, U)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(horiz, axis=0), axis=1))]
    secs = np.arange(np.ceil(t[0]), np.floor(t[-1]) + 1)
    gr = np.full(len(secs), np.nan)
    for i, ts in enumerate(secs):
        m = np.abs(t - ts) <= win / 2
        if m.sum() >= 4 and np.ptp(s[m]) > 0:
            gr[i] = 100 * np.polyfit(s[m], h[m], 1)[0]
    return secs.astype(int), gr


def gauss_nan(x: np.ndarray, sig: float) -> np.ndarray:
    """Gaussian smoothing that ignores NaN gaps; NaN where too little data."""
    ok = np.isfinite(x)
    num = gaussian_filter1d(np.where(ok, x, 0.0), sig, mode="constant")
    den = gaussian_filter1d(ok.astype(float), sig, mode="constant")
    return np.where(den > 0.3, num / np.maximum(den, 1e-9), np.nan)


def grade_per_second(video: Path, workdir: Path, duration: float, mask: Path | None, f: float) -> np.ndarray:
    """Grade [%] per video second (NaN where no SfM fragment covers it); caches gravity and reconstructions."""
    try:
        import pycolmap
    except ImportError as e:
        raise RuntimeError(
            "pycolmap není pro tuto platformu k dispozici (linux/aarch64) – použijte amd64 worker"
        ) from e

    gpath = workdir / "gravity.npy"
    if gpath.exists():
        grav = np.load(gpath)
    else:
        grav = gravity(str(video))
        np.save(gpath, grav)

    T = int(np.floor(duration)) + 1
    acc, cnt = np.zeros(T), np.zeros(T)
    for a, b in windows(0.0, duration, SFM_WINDOW_S, SFM_OVERLAP_S):
        report("rekonstrukce scény (SfM)", a, duration)
        best = None
        for model, fps in SFM_ATTEMPTS:
            work = workdir / "sfm" / f"{int(a)}_{fps:g}fps_{model}"
            done = work / "done"
            if done.exists():
                recs = [pycolmap.Reconstruction(p) for p in (work / "rec").iterdir() if p.is_dir()]
                ratio = float(done.read_text())
                res = [(r, ratio) for r in recs]
            else:
                res = sfm_window(video, work, a, b - a, fps, mask, f, model)
                ratio = res[0][1] if res else 0.0
                done.write_text(str(ratio))
            if best is None or ratio > best[0]:
                best = (ratio, fps, [r for r, _ in res])
            if ratio > 0.85:
                break
        _, fps, recs = best
        for rec in recs:
            if rec.num_reg_images() < MIN_IMAGES:
                continue
            res = fragment_grade(rec, a, fps, grav)
            if res is None:
                continue
            secs, gr = res
            v = gauss_nan(gr, GRADE_SIGMA_S)
            sel = np.isfinite(v) & (secs >= 0) & (secs < T)
            np.add.at(acc, secs[sel], v[sel])
            np.add.at(cnt, secs[sel], 1)
    return np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)


def video_profile(grade: np.ndarray, speed: np.ndarray) -> tuple[dict, np.ndarray]:
    """Profile from per-second grade [%] and speed [km/h]; returns (profile, distance per second)."""
    t = np.arange(len(grade), dtype=float)
    ok = np.isfinite(grade)
    if ok.sum() < 2:
        raise ValueError("sklon z videa se nepodařilo určit (žádný použitelný úsek SfM)")
    grade = np.interp(t, t[ok], grade[ok])
    d = np.r_[0, np.cumsum((speed[:-1] + speed[1:]) / 2 / 3.6)]
    elev = np.r_[0, np.cumsum(grade[:-1] / 100 * np.diff(d))]
    return build_profile(d, elev), d
