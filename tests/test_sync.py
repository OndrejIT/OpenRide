import cv2
import numpy as np
import pytest

from pipeline import sync


def motion(n, seed=1):
    return np.random.default_rng(seed).gamma(2, 1, n)


def test_offset_of_a_later_start():
    base = motion(12000)
    res = sync.offset(base[400:10000], base[:11000])  # data video starts 100 s into the played one
    assert res["offset_s"] == 100.0 and res["windows_agree"] == res["windows_sure"] == 40


def test_negative_offset():
    base = motion(12000)
    assert sync.offset(base[:10000], base[200:11000])["offset_s"] == -50.0


def test_differently_cut_videos_fail():
    base = motion(12000)
    play = np.r_[base[:4000], base[4800:11000]]  # 200 s missing in the middle
    with pytest.raises(ValueError, match="neshodují"):
        sync.offset(base[:10000], play)


def test_retime_shifts_and_clamps():
    timing = {"t": [0, 1, 2], "dist": [0.0, 10.0, 20.0]}
    assert sync.retime(timing, 1.0, 4) == {"t": [0, 1, 2, 3, 4], "dist": [0.0, 0.0, 10.0, 20.0, 20.0]}
    assert sync.retime(timing, -0.5, 2)["dist"] == [5.0, 15.0, 20.0]


def test_motion_energy_ignores_overlay_and_resolution(tmp_path):
    """Same moving scene, one copy with a changing overlay at the edge and half the resolution."""
    rng = np.random.default_rng(0)
    tex = cv2.GaussianBlur((rng.random((240, 3000)) * 255).astype(np.uint8), (7, 7), 0)
    speed = np.abs(np.cumsum(rng.normal(0, 1.5, 120))) + 1  # varying camera speed gives the signal its shape
    paths = []
    for name, size, overlay in (("data", (320, 240), True), ("play", (160, 120), False)):
        path = tmp_path / f"{name}.mp4"
        out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, size)
        x = 0.0
        for i in range(120):
            x += speed[i]
            frame = cv2.cvtColor(np.ascontiguousarray(tex[:, int(x) : int(x) + 320]), cv2.COLOR_GRAY2BGR)
            if overlay:
                cv2.putText(frame, f"{i % 37} km/h", (5, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            out.write(cv2.resize(frame, size))
        out.release()
        paths.append(path)
    a, b = (sync.motion_energy(str(p), hz=10) for p in paths)
    assert len(a) == len(b) == 120
    assert np.corrcoef(a[1:], b[1:])[0, 1] > 0.9
