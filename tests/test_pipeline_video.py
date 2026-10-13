import cv2
import numpy as np
import pytest

from pipeline import video_grade, vo
from pipeline.flow_speed import ground_mask


@pytest.fixture
def overlay_video(tmp_path):
    """Moving noise texture with a camera-fixed bright box (like a speed overlay)."""
    path = tmp_path / "v.mp4"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 180))
    rng = np.random.default_rng(0)
    tex = cv2.GaussianBlur((80 + rng.random((180, 1200)) * 100).astype(np.uint8), (9, 9), 0)
    for i in range(90):
        frame = cv2.cvtColor(np.ascontiguousarray(tex[:, i * 9 : i * 9 + 320]), cv2.COLOR_GRAY2BGR)
        cv2.rectangle(frame, (240, 20), (300, 60), (255, 255, 255), 2)
        cv2.putText(frame, "km/h", (245, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        out.write(frame)
    out.release()
    return path


def test_video_info_and_static_mask(overlay_video):
    fps, n, w, h = vo.video_info(str(overlay_video))
    assert (round(fps), n, w, h) == (30, 90, 320, 180)
    mask = vo.static_mask(str(overlay_video), samples=30)
    assert mask.shape == (180, 320)
    assert mask[40, 270] == 0  # overlay hidden
    assert (mask[:, :200] == 255).mean() > 0.95  # moving scenery kept


def test_ground_mask_respects_static():
    static = np.full((100, 200), 255, np.uint8)
    static[80:, 90:110] = 0
    m = ground_mask(200, 100, static)
    assert m[90, 100] == 0 and m[90, 50] == 255 and m[30, 100] == 0


def test_video_info_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError):
        vo.video_info(str(tmp_path / "nope.mp4"))


def test_windows_cover_range_with_overlap():
    w = video_grade.windows(0, 400, 150, 15)
    assert w[0] == (0, 150) and w[-1][1] == 400
    assert all(b - a == 150 for a, b in w)
    assert all(w[i + 1][0] < w[i][1] for i in range(len(w) - 1))


def test_gauss_nan_ignores_gaps():
    x = np.r_[np.full(50, 2.0), np.full(10, np.nan), np.full(50, 2.0), np.full(100, np.nan)]
    y = video_grade.gauss_nan(x, 3)
    assert np.allclose(y[:110][np.isfinite(y[:110])], 2.0)
    assert np.isnan(y[-50:]).all()


def test_geocalib_project_pinhole():
    d = np.array([[0.1, -0.2, 1.0]])
    px = video_grade.geocalib_project(d, np.array([500.0]), np.array([0.0]), (320, 180))
    assert px[0] == pytest.approx([370, 80])


def test_video_profile_integrates_grade():
    grade = np.r_[np.full(60, 4.0), np.nan, np.full(59, -2.0)]
    speed = np.full(120, 18.0)  # 5 m/s
    prof, d = video_grade.video_profile(grade, speed)
    assert d[-1] == pytest.approx(595)
    assert "lat" not in prof
    assert prof["elev"][20] == pytest.approx(8, abs=0.3)
    assert max(prof["grade"]) == pytest.approx(4, abs=0.2)


def test_video_profile_needs_grade():
    with pytest.raises(ValueError):
        video_grade.video_profile(np.full(10, np.nan), np.full(10, 20.0))
