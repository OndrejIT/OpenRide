import pytest
from django.test import Client

from routes.models import Ride, Route
from routes.rides import summary

pytestmark = pytest.mark.django_db


def samples(n=4, **override):
    s = {
        "t": list(range(n)),
        "dist": [0.0, 5.0, 3.0, 13.0][:n],  # a seek back must not count as riding
        "elev": [100.0, 101.0, 100.5, 102.0][:n],
        "grade": [2.0] * n,
        "sim": [1.0] * n,
        "brake": [5, 6, None, 6][:n],
        "power": [100, 150, None, 0][:n],
        "rpm": [80, 90, None, 0][:n],
        "pulse": [120, 130, None, 0][:n],
    }
    return {**s, **override}


def test_summary():
    s = summary(samples())
    assert s["duration_s"] == 4 and s["distance_m"] == 15.0 and s["elev_gain_m"] == 2.5
    assert s["avg_power"] == pytest.approx(83.3, abs=0.1) and s["max_power"] == 150
    assert s["avg_rpm"] == 85.0 and s["avg_pulse"] == 125.0 and s["max_pulse"] == 130


def test_summary_without_trainer():
    s = summary(samples(power=[None] * 4, rpm=[None] * 4, pulse=[None] * 4, brake=[None] * 4))
    assert s["avg_power"] is None and s["avg_rpm"] is None and s["max_pulse"] is None


def test_save_list_and_detail():
    route = Route.objects.create(title="Sankt Kassian")
    c = Client()
    data = {"route": route.pk, "started_at": "2026-10-13T18:00:00Z", "samples": samples()}
    r = c.post("/api/rides/", data, content_type="application/json")
    assert r.status_code == 201, r.content
    assert r.json()["title"] == "Sankt Kassian" and r.json()["distance_m"] == 15.0 and "samples" not in r.json()
    listed = c.get("/api/rides/").json()
    assert len(listed) == 1 and "samples" not in listed[0]
    detail = c.get(f"/api/rides/{listed[0]['id']}/").json()
    assert detail["samples"]["brake"] == [5, 6, None, 6]
    route.delete()  # the ride outlives its route
    assert Ride.objects.get().route is None


@pytest.mark.parametrize(
    "bad",
    [
        {"t": [0]},  # too short and other series missing
        samples(dist=[0, 1, 2]),  # length mismatch
        samples(elev=[0, None, 1, 2]),  # null only allowed in trainer series
        samples(power=[0, "x", 1, 2]),
    ],
)
def test_invalid_samples_are_rejected(bad):
    r = Client().post(
        "/api/rides/",
        {"route": None, "started_at": "2026-10-13T18:00:00Z", "samples": bad},
        content_type="application/json",
    )
    assert r.status_code == 400 and "samples" in r.json()
    assert not Ride.objects.exists()


def test_rides_cannot_be_deleted_through_the_api():
    ride = Ride.objects.create(title="x", started_at="2026-10-13T18:00:00Z", samples=samples(), **summary(samples()))
    assert Client().delete(f"/api/rides/{ride.pk}/").status_code == 405
