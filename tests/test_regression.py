"""Alignment on the prototype's real data (Deer Creek, Tyrol); skipped when the data is not available."""

import numpy as np
import pytest
from conftest import DATA_DIR

from pipeline import align, gpx

PERFECTION = DATA_DIR / "perfection"
TYROL = DATA_DIR / "tyrol_gpx"


def need(*paths):
    missing = [p for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"chybí data: {', '.join(map(str, missing))}")


def test_deer_creek_overlay_speed():
    """Short descent on a 140 km ride with several similar descents; overlay (OCR) speed, VO with a manual mask."""
    need(PERFECTION / "route.gpx", PERFECTION / "vo.npy", PERFECTION / "speed.csv")
    track = gpx.parse((PERFECTION / "route.gpx").read_bytes())
    sp = np.genfromtxt(PERFECTION / "speed.csv", delimiter=",", names=True)
    kmh = np.where(np.isfinite(sp["kmh"]), sp["kmh"], sp["mph"] * 1.609344)
    res = align.align(track, np.load(PERFECTION / "vo.npy"), 24000 / 1001, kmh, sp["t"], sp["t"][-1], relative=False)
    q = res["quality"]
    assert 85150 <= q["start_m"] <= 85300
    assert q["turn_corr"] >= 0.5
    assert (q["end_m"] - q["start_m"]) / 1000 == pytest.approx(3.75, abs=0.1)


@pytest.fixture(scope="module")
def tyrol():
    """31 min ride, relative ground-flow speed only (no OCR): scale and start found from turns."""
    need(TYROL / "route.gpx", TYROL / "flow.npy", DATA_DIR / "vo.npy")
    fps = 30000 / 1001
    track = gpx.parse((TYROL / "route.gpx").read_bytes())
    flow = np.load(TYROL / "flow.npy")
    return align.align(track, np.load(DATA_DIR / "vo.npy"), fps, flow[:, 2], flow[:, 0] / fps, 1859.5, relative=True)


def test_tyrol_flow_speed(tyrol):
    res = tyrol
    q = res["quality"]
    assert q["start_m"] == pytest.approx(9507.5, abs=10)
    assert (q["end_m"] - q["start_m"]) / 1000 == pytest.approx(15.95, abs=0.1)
    assert q["turn_corr"] >= 0.8
    proto = TYROL / "align_flow.npz"
    if proto.exists():  # same result as the prototype's dp run
        assert np.abs(res["d"] - np.load(proto)["d"]).max() < 10


def test_tyrol_flow_against_garmin_reference(tyrol):
    """Aligned speed vs the Garmin overlay speed read from the video (reference.csv)."""
    need(DATA_DIR / "reference.csv")
    res = tyrol
    ref = np.genfromtxt(DATA_DIR / "reference.csv", delimiter=",", names=True)
    ok = np.isfinite(ref["speed"])
    garmin = np.interp(res["t"], ref["t"][ok], ref["speed"][ok])
    assert res["quality"]["mean_kmh"] == pytest.approx(garmin.mean(), rel=0.05)
    assert np.corrcoef(res["speed"], garmin)[0, 1] > 0.5
