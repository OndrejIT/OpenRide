from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from routes import services, tasks
from routes.models import Route, Video

pytestmark = pytest.mark.django_db

URL = "/api/manage/videos/"


@pytest.fixture
def staff():
    client = Client(enforce_csrf_checks=True)
    client.force_login(get_user_model().objects.create_user("ondrej", password="x", is_staff=True))
    client.get("/api/manage/session/")  # sets the CSRF cookie like the dashboard does
    return client


def post(client, url, data=None, **kw):
    return client.post(url, data or {}, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value, **kw)


@pytest.fixture(autouse=True)
def yt_title():
    with mock.patch.object(services, "youtube_title", return_value="Sankt Kassian MTB") as title:
        yield title


@pytest.fixture
def send():
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        yield send


def test_session_reports_login_state(staff):
    anon = Client().get("/api/manage/session/").json()
    assert anon["user"] is None and not anon["is_staff"]
    me = staff.get("/api/manage/session/").json()
    assert me["user"] == "ondrej" and me["is_staff"]
    assert {"value": "overlay", "label": Video.GradeSource.OVERLAY.label} in me["grade_sources"]


def test_anonymous_and_non_staff_are_refused():
    assert Client().get(URL).status_code == 403
    user = Client()
    user.force_login(get_user_model().objects.create_user("host", password="x"))
    assert user.get(URL).status_code == 403


def test_add_and_process(staff, send):
    data = {"source_id": "https://youtu.be/y_g3yfhl0bo", "data_source_id": "G1EL9c91zQY", "grade_source": "overlay"}
    r = post(staff, URL, {**data, "process": "true"})
    assert r.status_code == 201, r.content
    v = r.json()
    assert v["title"] == "Sankt Kassian MTB" and v["status"] == "queued" and v["state"] == "čeká na worker"
    assert send.call_count == 1
    assert post(staff, f"{URL}{v['id']}/process/").status_code == 409  # already queued
    Video.objects.filter(pk=v["id"]).update(status=Video.Status.READY, quality={"method": "overlay", "grade_corr": 0.5})
    listed = staff.get(URL).json()[0]
    assert listed["verdict"] == "bad" and listed["quality"][1]["verdict"] == "bad"
    r = post(staff, f"{URL}{v['id']}/process/")
    assert r.status_code == 200 and r.json()["status"] == "queued" and send.call_count == 2
    r = post(staff, f"{URL}{v['id']}/stop/")
    assert r.status_code == 200 and r.json()["status"] == "failed" and r.json()["error"] == "ukončeno ručně"
    assert post(staff, f"{URL}{v['id']}/stop/").status_code == 409  # nothing to stop


def test_add_with_gpx_without_processing(staff, send, climb_gpx):
    data = {"source_id": "4Mmx8soDJ6s", "grade_source": "gpx", "gpx": SimpleUploadedFile("r.gpx", climb_gpx)}
    r = post(staff, URL, data)
    assert r.status_code == 201 and r.json()["has_gpx"] and r.json()["status"] == "new"
    assert Route.objects.get().profile and send.call_count == 0


def test_add_validation_errors(staff):
    r = post(staff, URL, {"source_id": "https://vimeo.com/1", "grade_source": "gpx"})
    assert r.status_code == 400
    assert "Neplatná URL" in r.json()["source_id"][0] and "vyžaduje GPX" in r.json()["gpx"][0]
    assert not Route.objects.exists()


def test_post_without_csrf_token_is_refused(staff):
    assert staff.post(URL, {"source_id": "4Mmx8soDJ6s", "grade_source": "video"}).status_code == 403
