import numpy as np
import pytest
from conftest import gpx_xml

from pipeline import align, gpx

FPS, STRIDE = 30.0, 5


def track_from_curvature(curv: np.ndarray, step: float = 5.0) -> gpx.Track:
    heading = np.cumsum(curv) * step  # compass, radians
    x = np.r_[0, np.cumsum(np.sin(heading[:-1]) * step)]
    y = np.r_[0, np.cumsum(np.cos(heading[:-1]) * step)]
    lat = 47 + y / 111195.0
    lon = 11 + x / (111195.0 * np.cos(np.radians(47)))
    return gpx.parse(gpx_xml(lat, lon, 500 + 0.02 * y))


def winding_road(length_m=20000.0, seed=1) -> gpx.Track:
    rng = np.random.default_rng(seed)
    n = int(length_m / 5)
    curv = np.zeros(n)
    for c in rng.integers(0, n - 40, 120):  # bends of 100-200 m with radius 40-150 m
        curv[c : c + rng.integers(20, 40)] += rng.choice([-1, 1]) / rng.uniform(40, 150)
    return track_from_curvature(curv)


def fake_video(track: gpx.Track, start_m: float, kmh: np.ndarray):
    """VO rows whose yaw follows the GPX heading along the ride, as the camera would see it."""
    grid = align.Grid.from_track(track)
    t = np.arange(len(kmh), dtype=float)
    d = start_m + np.r_[0, np.cumsum((kmh[:-1] + kmh[1:]) / 2 / 3.6)]
    frames = np.arange(0, len(kmh) * FPS - STRIDE, STRIDE)
    tf = (frames + STRIDE / 2) / FPS
    rate = align.YAW_SIGN * np.interp(tf, t, grid.turn_rate(d, kmh))
    vo = np.zeros((len(frames), 10))
    vo[:, 0], vo[:, 1], vo[:, 2], vo[:, 3] = frames, frames + STRIDE, 200, 5
    vo[:, 5] = rate * STRIDE / FPS
    vo[:, 9] = 1
    return vo, d, frames / FPS


@pytest.fixture(scope="module")
def ride():
    track = winding_road()
    t = np.arange(400)
    kmh = 30 + 8 * np.sin(t / 37.0)
    vo, d, tf = fake_video(track, 7000.0, kmh)
    return track, kmh, vo, d, tf


def test_align_absolute_speed(ride):
    track, kmh, vo, d, tf = ride
    res = align.align(track, vo, FPS, np.interp(tf, np.arange(len(kmh)), kmh), tf, len(kmh) - 1, relative=False)
    q = res["quality"]
    assert q["start_m"] == pytest.approx(7000, abs=15)
    assert q["turn_corr"] > 0.9
    assert np.abs(res["d"] - d).max() < 30


def test_align_relative_speed_finds_scale(ride):
    track, kmh, vo, d, tf = ride
    rng = np.random.default_rng(0)
    flow = 0.013 * np.interp(tf, np.arange(len(kmh)), kmh) * rng.normal(1, 0.05, len(tf))
    res = align.align(track, vo, FPS, flow, tf, len(kmh) - 1, relative=True)
    q = res["quality"]
    assert q["rigid_start_m"] == pytest.approx(7000, abs=50)
    assert q["start_m"] == pytest.approx(7000, abs=20)
    assert q["mean_kmh"] == pytest.approx(kmh.mean(), rel=0.05)
    assert np.all(np.diff(res["d"]) >= 0)


def test_dp_backtracking_beyond_int16_positions():
    # one sharp bend at km 85: the path index on the 2.5 m grid is > 32767 there
    n = 90000 // 5
    curv = np.zeros(n)
    curv[17000:17010] = (np.pi / 2) / 50
    track = track_from_curvature(curv)
    grid = align.Grid.from_track(track)
    kmh = np.full(30, 36.0)
    t = np.arange(30.0)
    yaw = align.YAW_SIGN * grid.turn_rate(85000 - 100 + 10 * t, kmh)
    d, _ = align.dp_align(grid, kmh, yaw, 1.0, 0.1, 0, track.length, track.length)
    assert d[10] == pytest.approx(85000, abs=30)
    assert np.all(np.diff(d) >= 0)


def test_speed_per_second_interpolates_gaps():
    ts = np.array([0.1, 0.6, 3.2, 3.7])
    sp = align.speed_per_second(np.array([10.0, 12.0, 20.0, 20.0]), ts, 4.0, relative=False)
    assert len(sp) == 5
    assert sp.min() >= 11 and sp.max() <= 20  # per-second medians 11, 20; gap interpolated, median filtered


def test_speed_per_second_requires_samples():
    with pytest.raises(ValueError):
        align.speed_per_second(np.array([np.nan, np.nan]), np.array([0.0, 1.0]), 2.0, relative=True)
