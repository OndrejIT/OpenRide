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


def raw(items):
    return [t for t, _ in items], [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for _, (x0, y0, x1, y1) in items]


def ocr_frame(items, layout="units"):
    return overlay.LAYOUTS[layout].tokens(*raw(items))


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


def test_tokens_signed_grade():
    assert [v for _, v, _, _ in ocr_frame([("+17%", (25, 625, 115, 645))])] == [17.0]
    assert [v for _, v, _, _ in ocr_frame([("−3 %", (25, 655, 115, 675))])] == [-3.0]
    assert [v for _, v, _, _ in ocr_frame([("+2.4%", (1082, 526, 1220, 597))])] == [2.4]


# Stelvio video, 0:26: the unit "M" sits left below the value, "%" is mostly not read at all
STELVIO = [
    ("ELEVATION", (68, 38, 203, 64)),
    ("2929", (65, 68, 198, 118)),
    ("M", (66, 122, 97, 149)),
    ("SLOPE", (72, 198, 153, 218)),
    ("-5", (69, 222, 130, 270)),
    ("22.6", (315, 568, 441, 621)),
    ("KM", (358, 618, 395, 641)),
]


def test_tokens_from_labelled_overlay():
    found = {f: v for f, v, _, _ in ocr_frame(STELVIO, "labels")}
    assert found == {"elev": 2929.0, "grade": -5.0, "dist": 22.6}
    # the plain layout keeps its strict rules
    assert {f for f, *_ in ocr_frame(STELVIO)} == {"dist"}


def test_pick_layout_per_overlay():
    assert overlay.pick_layout([raw(FRAME)] * 3).name == "units"  # equal reads: the plain layout
    assert overlay.pick_layout([raw(STELVIO)] * 3).name == "labels"
    assert overlay.pick_layout([]).name == "units"


def test_tokens_from_merged_readouts():
    toks = ocr_frame([("4 rpm 23 km/h2.6 km", (700, 640, 960, 670))])
    assert [(f, v) for f, v, _, _ in toks] == [("speed", 23.0), ("dist", 2.6)]
    assert toks[0][2] < toks[1][2]  # each value at its own part of the box


def test_select_takes_the_growing_distance():
    # a lap distance stuck at 0.0 km is read more often than the odometer
    frames = [[("dist", 0.0, 240, 640)] + ([("dist", i / 10, 880, 640)] if i % 2 else []) for i in range(60)]
    assert np.nanmax(overlay.select(frames, 720)[:, 1]) == 5.9
    # nothing that grows (lap distance, route length): no distance rather than a wrong one
    assert np.isnan(overlay.select([[("dist", 0.0, 240, 640), ("dist", 41.9, 880, 640)]] * 30, 720)[:, 1]).all()


def test_frame_tokens_from_raw_cache():
    data = {"texts": [["2.5km", "3%"]], "boxes": [[[1093, 611], [1167, 652]], [[1114, 693], [1150, 719]]]}
    data["boxes"] = [data["boxes"]]
    assert {f for f, *_ in overlay.frame_tokens(data, overlay.layout_of(data))[0]} == {"dist", "grade"}


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
    with pytest.raises(ValueError, match="přečíst rychlost"):
        overlay.ride(t, values)


def test_ride_rejects_scattered_odometer_without_speed():
    # Spain telemetry: speed in 40 % of frames, the "km" readings a few misreads of other widgets
    t, _, values = synthetic_ride()
    values[np.arange(len(t)) % 5 != 0, 0] = np.nan
    values[np.arange(len(t)) % 10 != 0, 1] = np.nan
    with pytest.raises(ValueError, match=r"rychlost \(20 %\) ani vzdálenost \(10 %\)"):
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
