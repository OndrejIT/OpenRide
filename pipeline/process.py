"""End-to-end processing of one downloaded video; small intermediate results are cached in `workdir`."""

import json
import logging
from pathlib import Path

import numpy as np

from pipeline import align, gpx, vo
from pipeline.flow_speed import ground_mask, ground_speed

log = logging.getLogger(__name__)

VO_FPS = 6.0
# POV footage often shows handlebars/rider moving independently of the scene at the bottom; rotation is best
# measured on distant scenery anyway (Deer Creek + overlay speed: full-frame VO aligns 50 km off, top 60 % correct)
VO_TOP = 0.6


def _cached(path: Path, compute):
    if path.exists():
        return np.load(path)
    arr = compute()
    np.save(path, arr)
    return arr


def motion(video: Path, workdir: Path) -> dict:
    """Intrinsics, overlay mask, VO and ground flow of the video."""
    import cv2

    from pipeline.video_grade import estimate_intrinsics

    fps, n, w, h = vo.video_info(str(video))
    cam_path = workdir / "intrinsics.json"
    if cam_path.exists():
        f, k1 = json.loads(cam_path.read_text())
    else:
        f, k1 = estimate_intrinsics(str(video))
        cam_path.write_text(json.dumps([f, k1]))
    mask_path = workdir / "mask.png"
    if mask_path.exists():
        static = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    else:
        static = vo.static_mask(str(video))
        cv2.imwrite(str(mask_path), static)
    stride = max(1, round(fps / VO_FPS))
    log.info("video %dx%d %.3f fps %d frames, f=%.0f k1=%.3f, VO stride %d", w, h, fps, n, f, k1, stride)
    vo_mask = static.copy()
    vo_mask[int(VO_TOP * h) :] = 0
    scene_mask = workdir / "scene_mask.png"  # also keeps SfM features off the bike
    cv2.imwrite(str(scene_mask), vo_mask)
    vo_rows = _cached(workdir / "vo.npy", lambda: vo.relative_poses(str(video), f, k1, stride, vo_mask))
    flow = _cached(workdir / "flow.npy", lambda: ground_speed(str(video), vo_rows, f, k1, ground_mask(w, h, static)))
    return {"fps": fps, "duration": n / fps, "f": f, "k1": k1, "scene_mask": scene_mask, "vo": vo_rows, "flow": flow}


def timing(t: np.ndarray, d: np.ndarray) -> dict:
    return {"t": t.astype(int).tolist(), "dist": np.round(d, 1).tolist()}


def process_gpx(video: Path, workdir: Path, track: gpx.Track) -> dict:
    """Align the GPX to the video; profile = the aligned GPX section, timing relative to its start."""
    m = motion(video, workdir)
    fl = m["flow"]
    res = align.align(track, m["vo"], m["fps"], fl[:, 2], fl[:, 0] / m["fps"], m["duration"], relative=True)
    d = res["d"]
    profile, offset = gpx.track_profile(track, d[0], d[-1])
    return {
        "duration_s": int(round(m["duration"])),
        "profile": profile,
        "timing": timing(res["t"], d - offset),
        "quality": res["quality"],
    }


def process_video_grade(video: Path, workdir: Path, assumed_kmh: float) -> dict:
    """Grade from the video alone; distance from ground flow scaled to an assumed mean speed (no absolute scale)."""
    from pipeline.video_grade import grade_per_second, video_profile

    m = motion(video, workdir)
    fl = m["flow"]
    speed = align.speed_per_second(fl[:, 2], fl[:, 0] / m["fps"], m["duration"], relative=True)
    speed *= assumed_kmh / speed.mean()
    grade = grade_per_second(video, workdir, m["duration"], m["scene_mask"], m["f"])
    profile, d = video_profile(grade, speed)
    return {
        "duration_s": int(round(m["duration"])),
        "profile": profile,
        "timing": timing(np.arange(len(d), dtype=float), d),
        "quality": {
            "method": "video",
            "assumed_kmh": assumed_kmh,
            "grade_coverage": round(float(np.isfinite(grade).mean()), 3),
        },
    }


def process_overlay(video: Path, workdir: Path) -> dict:
    """Profile and timing read from the bike computer overlay burned into the video; no GPX, no alignment."""
    from pipeline import overlay

    fps, n, _, _ = vo.video_info(str(video))
    data = overlay.cached_ocr(video, workdir)
    profile, d, quality = overlay.ride(data["t"], overlay.select(data["frames"], data["height"]))
    return {
        "duration_s": int(round(n / fps)),
        "profile": profile,
        "timing": timing(np.arange(len(d), dtype=float), d),
        "quality": quality,
    }


def sync_videos(data: Path, play: Path, workdir: Path) -> dict:
    """Offset between the processed and the played upload of the same ride, plus the played video's duration."""
    from pipeline import sync

    signals = [
        _cached(workdir / f"motion_{p.stem}.npy", lambda p=p, s=s: sync.motion_energy(str(p), step=s))
        for p, s in ((data, "synchronizace: zpracovávané video"), (play, "synchronizace: přehrávané video"))
    ]
    fps, n, _, _ = vo.video_info(str(play))
    return {**sync.offset(*signals), "duration_s": int(round(n / fps))}


def apply_sync(result: dict, sync_info: dict) -> dict:
    """Result of the processed video -> timing and duration of the played one."""
    from pipeline import sync

    duration = sync_info["duration_s"]
    sync_quality = {k: v for k, v in sync_info.items() if k != "duration_s"}
    return {
        **result,
        "duration_s": duration,
        "timing": sync.retime(result["timing"], sync_info["offset_s"], duration),
        "quality": {**result["quality"], "sync": sync_quality},
    }
