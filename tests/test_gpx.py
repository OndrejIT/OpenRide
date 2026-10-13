import numpy as np
import pytest
from conftest import gpx_xml, straight_climb

from pipeline import gpx


def test_parse_namespaced_track_drops_duplicates():
    xml = gpx_xml([50.0, 50.0, 50.001, 50.002], [14.0] * 4, [100, 100, 101, 102])
    t = gpx.parse(xml)
    assert len(t.lat) == 3
    assert t.length == pytest.approx(222.4, abs=0.5)


def test_parse_route_points_and_attribute_order():
    xml = b"""<gpx><rte><rtept lon="14.0" lat="50.0"><ele>1</ele></rtept>
    <rtept lon="14.0" lat="50.001"><ele>2</ele></rtept></rte></gpx>"""
    t = gpx.parse(xml)
    assert t.lat.tolist() == [50.0, 50.001]


@pytest.mark.parametrize("xml", [b"<gpx/>", b"<gpx><trk><trkseg><trkpt lat='1' lon='1'/></trkseg></trk></gpx>"])
def test_parse_rejects_tracks_without_elevation(xml):
    with pytest.raises(ValueError):
        gpx.parse(xml)


def test_profile_constant_grade_and_summary():
    t = gpx.parse(straight_climb(2000, 5.0))
    prof, offset = gpx.track_profile(t)
    assert offset == 0
    assert prof["step_m"] == 10
    assert prof["dist"][:3] == [0, 10, 20]
    assert len({len(prof[k]) for k in ("dist", "elev", "grade", "lat", "lon")}) == 1
    inner = np.array(prof["grade"][10:-10])
    assert np.allclose(inner, 5.0, atol=0.15)
    s = gpx.summary(prof)
    assert s["distance_km"] == pytest.approx(1.99, abs=0.01)
    assert s["elev_gain_m"] == pytest.approx(99, abs=3)
    assert s["elev_loss_m"] == 0
    assert s["max_grade"] == pytest.approx(5.0, abs=0.2)


def test_track_profile_section_offset():
    t = gpx.parse(straight_climb(2000, 5.0))
    prof, offset = gpx.track_profile(t, 503.0, 1204.0)
    assert offset == 500
    assert prof["dist"][0] == 0
    assert prof["dist"][-1] == 710  # up to the first grid point at or after the end (1210 m)
    assert prof["elev"][0] == pytest.approx(225, abs=0.5)


def test_build_profile_without_positions():
    prof = gpx.build_profile([0, 100, 250], [0, 10, 25])
    assert "lat" not in prof
    assert prof["dist"][-1] == 250
    assert np.allclose(prof["grade"][10:-10], 10, atol=0.3)


def test_simplify_keeps_corners_only():
    lat = np.r_[np.linspace(50, 50.01, 50), np.full(50, 50.01)]
    lon = np.r_[np.full(50, 14.0), np.linspace(14.0, 14.01, 50)]
    seg = gpx.simplify(lat, lon, 5.0)
    assert seg == [[50.0, 14.0], [50.01, 14.0], [50.01, 14.01]]
