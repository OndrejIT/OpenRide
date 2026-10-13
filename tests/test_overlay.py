import numpy as np
import pytest

from pipeline import overlay

# texts and boxes as RapidOCR reads a 720p Garmin overlay frame (Sankt Kassian video, 10:00)
FRAME = [
    ("Hōhe1668.2m", (1006, 546, 1157, 582)),
    ("TEMPERATUR", (1197, 555, 1272, 568)),
    ("22℃", (1195, 565, 1246, 587)),
    ("10", (85, 594, 137, 638)),
    ("2.5km", (1093, 611, 1167, 652)),
    ("km/h", (89, 632, 131, 653)),
    ("TRITTFREQUENZ", (577, 676, 676, 692)),
    ("1,09.202", (14, 694, 60, 714)),
    ("59 1/MIN", (573, 687, 658, 713)),
    ("3%", (1114, 693, 1150, 719)),
]


def ocr_frame(items):
    boxes = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for _, (x0, y0, x1, y1) in items]
    return overlay.tokens([t for t, _ in items], boxes)


def test_tokens_from_garmin_frame():
    found = {f: v for f, v, _, _ in ocr_frame(FRAME)}
    assert found == {"elev": 1668.2, "dist": 2.5, "speed": 10.0, "grade": 3.0}


def test_tokens_split_label_and_negative_grade():
    found = {
        f: v
        for f, v, _, _ in ocr_frame(
            [
                ("Hōhe", (1009, 549, 1053, 574)),
                ("1668.2M", (1040, 543, 1156, 583)),
                ("-4%", (1114, 693, 1150, 719)),
                ("12,5 km", (1093, 611, 1167, 652)),
            ]
        )
    }
    assert found == {"elev": 1668.2, "grade": -4.0, "dist": 12.5}


def test_select_ignores_matches_away_from_the_readout():
    frames = [[("speed", 20.0, 100, 600)], [("speed", 21.0, 104, 600), ("speed", 50.0, 900, 100)], []]
    out = overlay.select(frames + [[("speed", 22.0, 98, 601)]], 720)
    assert out[:, 0].tolist()[:2] == [20.0, 21.0] and np.isnan(out[2, 0]) and out[3, 0] == 22.0
    assert np.isnan(out[:, 1:]).all()


def synthetic_ride(n=900, kmh=18.0):
    t = np.arange(n, dtype=float)
    d = kmh / 3.6 * t
    elev = 1000 + 40 * np.sin(d / 800)  # up to ±5 %
    grade = 100 * 40 / 800 * np.cos(d / 800)
    values = np.c_[np.full(n, kmh), np.floor(d / 100) / 10, np.round(elev, 1), np.round(grade)]
    return t, d, values


def test_ride_profile_and_timing():
    t, d, values = synthetic_ride()
    values[::50, 2] += 20  # misread digit in the elevation
    values[::7, 0] = np.nan  # unreadable frames
    profile, dist, q = overlay.ride(t, values)
    assert len(dist) == len(t) and dist[0] == 0
    assert dist[-1] == pytest.approx(d[-1], abs=20)
    assert max(profile["elev"]) - min(profile["elev"]) == pytest.approx(80, abs=4)
    assert q["method"] == "overlay" and q["elev_source"] == "elev"
    assert q["grade_corr"] > 0.95 and q["dist_scale"] == pytest.approx(1.0, abs=0.02)


def test_ride_calibrates_wrong_speed_to_the_odometer():
    t, d, values = synthetic_ride()
    values[:, 0] *= 1.1  # speed readout 10 % high
    _, dist, q = overlay.ride(t, values)
    assert dist[-1] == pytest.approx(d[-1], abs=30)
    assert q["dist_scale"] == pytest.approx(1 / 1.1, abs=0.02)


def test_ride_falls_back_to_grade_without_elevation():
    t, _, values = synthetic_ride()
    values[:, 2] = np.nan
    profile, _, q = overlay.ride(t, values)
    assert q["elev_source"] == "grade"
    assert max(profile["grade"]) == pytest.approx(5, abs=1)


def test_ride_without_speed_and_distance_fails():
    t, _, values = synthetic_ride()
    values[:, :2] = np.nan
    with pytest.raises(ValueError, match="rychlost ani vzdálenost"):
        overlay.ride(t, values)


def test_ride_jumps_over_a_cut_in_the_video():
    t, d, values = synthetic_ride(n=1200)
    keep = (t < 500) | (t >= 600)  # 100 s (500 m) cut out of the video
    values, true_d = values[keep], d[keep]
    t = np.arange(len(values), dtype=float)
    profile, dist, q = overlay.ride(t, values)
    assert q["cuts_s"] == [500]
    assert dist[-1] == pytest.approx(true_d[-1], abs=30)
    assert max(np.abs(profile["grade"])) < 6  # no spike where elevation jumps
