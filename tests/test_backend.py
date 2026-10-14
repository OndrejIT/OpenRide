import io
import time
from unittest import mock
from urllib.error import HTTPError, URLError

import dramatiq
import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import IntegrityError
from django.urls import reverse

from routes import services, tasks
from routes.models import Route, Video

pytestmark = pytest.mark.django_db


def make_route(climb_gpx=None, **kw) -> Route:
    route = Route(title=kw.pop("title", "Trasa"), **kw)
    if climb_gpx:
        route.gpx = SimpleUploadedFile("r.gpx", climb_gpx)
        route.save()
        services.apply_gpx(route)
    route.save()
    return route


# ---------- models / services ----------


@pytest.mark.parametrize(
    "value",
    [
        "https://www.youtube.com/watch?v=4Mmx8soDJ6s&t=10s",
        "https://youtu.be/4Mmx8soDJ6s?si=x",
        "youtube.com/shorts/4Mmx8soDJ6s",
        "https://www.youtube.com/embed/4Mmx8soDJ6s",
        "https://m.youtube.com/watch?v=4Mmx8soDJ6s",
        " 4Mmx8soDJ6s ",
    ],
)
def test_parse_youtube_id(value):
    assert services.parse_youtube_id(value) == "4Mmx8soDJ6s"


@pytest.mark.parametrize("value", ["https://vimeo.com/123", "https://www.youtube.com/watch?v=short", "nonsense"])
def test_parse_youtube_id_rejects(value):
    with pytest.raises(ValueError):
        services.parse_youtube_id(value)


def test_apply_gpx_fills_profile_and_summary(climb_gpx):
    route = make_route(climb_gpx)
    assert route.profile["step_m"] == 10
    assert {"lat", "lon"} <= route.profile.keys()
    assert route.distance_km == pytest.approx(1.99, abs=0.01)
    assert route.max_grade == pytest.approx(5.0, abs=0.2)
    assert route.segment[0] == pytest.approx([50.0, 14.0])
    assert len(route.segment) == 2  # straight line


def test_video_grade_source_gpx_requires_gpx():
    route = make_route()
    video = Video(route=route, source_id="4Mmx8soDJ6s", grade_source=Video.GradeSource.GPX)
    with pytest.raises(ValidationError) as e:
        video.full_clean()
    assert "grade_source" in e.value.message_dict
    Video(route=route, source_id="4Mmx8soDJ6s", grade_source=Video.GradeSource.VIDEO).full_clean()


def test_video_source_id_unique(climb_gpx):
    Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s")
    with pytest.raises(IntegrityError):
        Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s")


# ---------- API ----------


def test_api_lists_only_rideable_routes(client, climb_gpx):
    virtual = make_route(climb_gpx, title="A virtual")
    ready = make_route(climb_gpx, title="B ready")
    Video.objects.create(
        route=ready, source_id="4Mmx8soDJ6s", status=Video.Status.READY, duration_s=60, timing={"t": [0], "dist": [0]}
    )
    pending = make_route(climb_gpx, title="C pending")
    Video.objects.create(route=pending, source_id="aaaaaaaaaaa")
    make_route(title="D no profile")

    data = client.get("/api/routes/").json()
    assert [r["title"] for r in data] == ["A virtual", "B ready"]
    assert data[0]["video"] is None
    assert data[1]["video"] == {"source": "youtube", "source_id": "4Mmx8soDJ6s", "duration_s": 60}
    assert set(data[0]) == {"id", "title", "distance_km", "elev_gain_m", "elev_loss_m", "max_grade", "video"}

    detail = client.get(f"/api/routes/{ready.pk}/").json()
    assert detail["video"]["timing"] == {"t": [0], "dist": [0]}
    assert detail["profile"]["step_m"] == 10
    assert detail["segment"]
    assert client.get(f"/api/routes/{virtual.pk}/").json()["video"] is None
    assert client.get(f"/api/routes/{pending.pk}/").status_code == 404


def test_api_is_read_only(client, climb_gpx):
    route = make_route(climb_gpx)
    assert client.post("/api/routes/", {}).status_code == 405
    assert client.delete(f"/api/routes/{route.pk}/").status_code == 405


# ---------- admin ----------


@pytest.fixture
def admin(admin_client):
    return admin_client


def route_post(gpx=None, video=None, **extra):
    data = {
        "title": "Deer Creek",
        "video-TOTAL_FORMS": "1",
        "video-INITIAL_FORMS": "0",
        "video-MIN_NUM_FORMS": "0",
        "video-MAX_NUM_FORMS": "1",
        **extra,
    }
    if gpx is not None:
        data["gpx"] = SimpleUploadedFile("route.gpx", gpx)
    if video:
        data.update({f"video-0-{k}": v for k, v in video.items()})
    return data


def video_post(gpx=None, **kw):
    data = {"source": "youtube", "source_id": "https://youtu.be/y_g3yfhl0bo", "data_source_id": "", **kw}
    if gpx is not None:
        data["gpx"] = SimpleUploadedFile("route.gpx", gpx)
    return data


@pytest.fixture
def yt_title():
    with mock.patch.object(services, "youtube_title", return_value="Sankt Kassian MTB") as title:
        yield title


def test_admin_video_add_creates_route_with_youtube_title(admin, yt_title):
    r = admin.post(reverse("admin:routes_video_add"), video_post(grade_source="overlay"))
    assert r.status_code == 302, r.content
    yt_title.assert_called_once_with("y_g3yfhl0bo")
    v = Video.objects.select_related("route").get()
    assert v.route.title == "Sankt Kassian MTB" and v.status == Video.Status.NEW
    assert v.route.profile is None and not v.route.gpx
    assert admin.get(reverse("admin:routes_video_change", args=[v.pk])).status_code == 200
    assert admin.get(reverse("admin:routes_video_changelist")).status_code == 200


def test_admin_video_add_with_gpx_computes_route_profile(admin, yt_title, climb_gpx):
    r = admin.post(reverse("admin:routes_video_add"), video_post(climb_gpx, grade_source="gpx"))
    assert r.status_code == 302, r.content
    route = Video.objects.get().route
    assert route.gpx and route.profile and route.segment and route.distance_km == pytest.approx(2.0, abs=0.05)


def test_admin_video_add_with_separate_data_video(admin, yt_title):
    data = video_post(grade_source="overlay", data_source_id="https://www.youtube.com/watch?v=G1EL9c91zQY")
    assert admin.post(reverse("admin:routes_video_add"), data).status_code == 302
    v = Video.objects.get()
    assert (v.source_id, v.data_source_id) == ("y_g3yfhl0bo", "G1EL9c91zQY")


def test_admin_video_add_gpx_source_requires_gpx(admin, yt_title):
    r = admin.post(reverse("admin:routes_video_add"), video_post(grade_source="gpx"))
    assert r.status_code == 200 and "vyžaduje GPX" in r.content.decode()
    assert not Route.objects.exists()


def test_admin_video_add_rejects_invalid_input(admin):
    with mock.patch.object(services, "youtube_title", side_effect=ValueError("Video na YouTube neexistuje")):
        r = admin.post(reverse("admin:routes_video_add"), video_post(b"<gpx/>", grade_source="gpx"))
        assert "neexistuje" in r.content.decode() and "Neplatný GPX" in r.content.decode()
        r = admin.post(
            reverse("admin:routes_video_add"), video_post(source_id="https://vimeo.com/1", grade_source="video")
        )
    assert r.status_code == 200 and "Neplatná URL" in r.content.decode()
    assert not Route.objects.exists()


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (None, "Ride"),
        (URLError("offline"), "y_g3yfhl0bo"),
        (HTTPError("u", 500, "err", {}, None), "y_g3yfhl0bo"),
    ],
)
def test_youtube_title(effect, expected):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(b'{"title": "Ride"}')
    with mock.patch("routes.services.urlopen", return_value=resp, side_effect=effect):
        assert services.youtube_title("y_g3yfhl0bo") == expected


def test_youtube_title_unavailable():
    with (
        mock.patch("routes.services.urlopen", side_effect=HTTPError("u", 401, "Unauthorized", {}, None)),
        pytest.raises(ValueError, match="nejde vložit"),
    ):
        services.youtube_title("y_g3yfhl0bo")


def test_admin_route_add_is_a_virtual_ride(admin, climb_gpx):
    r = admin.get(reverse("admin:routes_route_add"))
    assert "video-TOTAL_FORMS" not in r.content.decode()  # videos are added under Videa
    r = admin.post(reverse("admin:routes_route_add"), {"title": "Okruh"})
    assert r.status_code == 200 and "Videa → Přidat" in r.content.decode()
    r = admin.post(reverse("admin:routes_route_add"), {"title": "Okruh", "gpx": SimpleUploadedFile("r.gpx", climb_gpx)})
    assert r.status_code == 302 and Route.objects.get().profile


def test_admin_route_edit_without_video_still_requires_gpx(admin, yt_title):
    admin.post(reverse("admin:routes_video_add"), video_post(grade_source="overlay"))
    route = Route.objects.get()
    data = route_post(None, None, **{"video-INITIAL_FORMS": "1", "video-0-id": str(route.video.pk)})
    data.update({"video-0-route": str(route.pk), "video-0-source": "youtube", "video-0-source_id": "y_g3yfhl0bo"})
    data.update({"video-0-grade_source": "overlay", "video-0-DELETE": "on"})
    r = admin.post(reverse("admin:routes_route_change", args=[route.pk]), data)
    assert r.status_code == 200 and "vyžaduje GPX" in r.content.decode()


def test_admin_new_gpx_resets_processed_video(admin, climb_gpx):
    route = make_route(climb_gpx)
    video = Video.objects.create(route=route, source_id="4Mmx8soDJ6s", status=Video.Status.READY, timing={"t": []})
    data = route_post(climb_gpx, None, **{"video-INITIAL_FORMS": "1", "video-0-id": str(video.pk)})
    data.update({"video-0-route": str(route.pk), "video-0-source": "youtube", "video-0-source_id": "4Mmx8soDJ6s"})
    data["video-0-grade_source"] = "gpx"
    r = admin.post(reverse("admin:routes_route_change", args=[route.pk]), data)
    assert r.status_code == 302, r.content
    video.refresh_from_db()
    assert video.status == Video.Status.NEW and video.timing is None


def test_admin_changelist_renders(admin, climb_gpx):
    Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s")
    assert admin.get(reverse("admin:routes_route_changelist")).status_code == 200


# ---------- processing ----------


@pytest.fixture(autouse=True)
def video_info():
    # downloads are mocked, so the video length for the time limit is too: 1 h at 30 fps
    with mock.patch("pipeline.vo.video_info", return_value=(30.0, 108000, 1280, 720)) as info:
        yield info


def test_enqueue_marks_queued_and_reverts_when_the_broker_is_down(climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s", status=Video.Status.READY)
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        tasks.enqueue(video)
    video.refresh_from_db()
    assert send.call_args.kwargs["args"] == (video.pk, video.task_token) and len(video.task_token) == 32
    assert Video.objects.get(pk=video.pk).status == Video.Status.QUEUED
    with (
        mock.patch.object(tasks.process_video, "send_with_options", side_effect=ConnectionError),
        pytest.raises(ConnectionError),
    ):
        Video.objects.filter(pk=video.pk).update(status=Video.Status.READY)
        tasks.enqueue(video)
    assert Video.objects.get(pk=video.pk).status == Video.Status.READY
    assert tasks.process_video.options["max_retries"] == 0


def test_time_limit_follows_video_length():
    video = Video(grade_source=Video.GradeSource.GPX)
    assert tasks.time_limit_s(video, 600) == 3600  # minimum
    assert tasks.time_limit_s(video, 3600) == 7200
    video.grade_source = Video.GradeSource.VIDEO
    assert tasks.time_limit_s(video, 3600) == 8 * 3600


def test_progress_is_throttled_and_enforces_the_limit(climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s")
    progress = tasks.Progress(video.pk)
    with mock.patch("routes.tasks.time.time", return_value=1000.0):
        progress("vizuální odometrie", 10.0)
        progress("vizuální odometrie", 20.0)  # within the interval: not written
    assert Video.objects.get(pk=video.pk).progress == {"step": "vizuální odometrie", "pct": 10.0, "since": 1000}
    with mock.patch("routes.tasks.time.time", return_value=1006.0):
        progress("vizuální odometrie", 30.0)
        progress("rychlost z obrazu", 0.0)  # a new step is written at once
    assert Video.objects.get(pk=video.pk).progress == {"step": "rychlost z obrazu", "pct": 0.0, "since": 1006}
    progress.started = 0.0
    progress.set_limit(3600)
    with pytest.raises(tasks.ProcessingTimeout, match="60 min"):
        progress("rychlost z obrazu", 50.0)


def test_process_video_success(climb_gpx):
    route = make_route(climb_gpx)
    video = Video.objects.create(route=route, source_id="4Mmx8soDJ6s")
    result = {
        "duration_s": 120,
        "profile": route.profile,
        "timing": {"t": [0, 1], "dist": [0.0, 8.3]},
        "quality": {"method": "dp", "turn_corr": 0.8},
    }
    with (
        mock.patch("pipeline.download.download") as dl,
        mock.patch("pipeline.process.process_gpx", return_value=result) as proc,
    ):
        dl.return_value.unlink = mock.Mock()
        tasks.process_video.fn(video.pk)
    proc.assert_called_once()
    dl.return_value.unlink.assert_called_once()  # downloaded video is deleted
    video.refresh_from_db()
    assert video.status == Video.Status.READY
    assert video.duration_s == 120 and video.quality["turn_corr"] == 0.8
    assert video.started_at and video.finished_at >= video.started_at and video.progress is None


def test_process_video_overlay_without_gpx():
    route = make_route()
    video = Video.objects.create(route=route, source_id="G1EL9c91zQY", grade_source=Video.GradeSource.OVERLAY)
    video.full_clean()  # overlay needs no GPX
    profile = {"step_m": 10, "dist": [0.0, 10.0, 20.0], "elev": [100.0, 100.5, 101.0], "grade": [5.0, 5.0, 5.0]}
    result = {"duration_s": 3, "profile": profile, "timing": {"t": [0, 1, 2], "dist": [0.0, 10.0, 20.0]}, "quality": {}}
    with (
        mock.patch("pipeline.download.download"),
        mock.patch("pipeline.process.process_overlay", return_value=result) as proc,
    ):
        tasks.process_video.fn(video.pk)
    proc.assert_called_once()
    route.refresh_from_db()
    assert route.segment is None and route.distance_km == 0.02 and route.max_grade == 5.0
    assert Video.objects.get(pk=video.pk).status == Video.Status.READY


def test_process_video_from_data_video_is_retimed_to_the_played_one():
    route = make_route()
    video = Video.objects.create(
        route=route, source_id="y_g3yfhl0bo", data_source_id="G1EL9c91zQY", grade_source=Video.GradeSource.OVERLAY
    )
    profile = {"step_m": 10, "dist": [0.0, 10.0, 20.0], "elev": [100.0, 100.5, 101.0], "grade": [5.0, 5.0, 5.0]}
    result = {"duration_s": 3, "profile": profile, "timing": {"t": [0, 1, 2], "dist": [0.0, 10.0, 20.0]}, "quality": {}}
    sync = {"offset_s": 1.0, "corr": 0.9, "duration_s": 4}
    with (
        mock.patch("pipeline.download.download") as dl,
        mock.patch("pipeline.process.process_overlay", return_value=result),
        mock.patch("pipeline.process.sync_videos", return_value=sync),
    ):
        tasks.process_video.fn(video.pk)
    assert [c.args[0] for c in dl.call_args_list] == ["G1EL9c91zQY", "y_g3yfhl0bo"]
    assert dl.call_args_list[1].kwargs["height"] == 360
    video.refresh_from_db()
    assert video.status == Video.Status.READY
    assert video.duration_s == 4 and video.timing == {"t": [0, 1, 2, 3, 4], "dist": [0.0, 0.0, 10.0, 20.0, 20.0]}
    assert video.quality["sync"] == {"offset_s": 1.0, "corr": 0.9}


def test_process_video_failure_is_recorded_with_the_step(climb_gpx):
    from pipeline.progress import report

    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s")

    def fail(*args, **kwargs):
        report("stahování videa", 5, 10)
        raise RuntimeError("HTTP 403")

    with mock.patch("pipeline.download.download", side_effect=fail), pytest.raises(RuntimeError):
        tasks.process_video.fn(video.pk)
    video.refresh_from_db()
    assert video.status == Video.Status.FAILED and video.finished_at and video.progress is None
    assert video.error == "stahování videa: RuntimeError: HTTP 403"


def test_stopped_video_ends_its_running_task(climb_gpx):
    from pipeline.progress import report

    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s", task_token="t")

    def download(*args, **kwargs):
        report("stahování videa", 1, 10)
        tasks.cancel(Video.objects.get(pk=video.pk))  # the admin stops it while it runs
        report("OCR overlaye", 2, 10)
        raise AssertionError("not reached")

    with mock.patch("pipeline.download.download", side_effect=download):
        tasks.process_video.fn(video.pk, "t")  # ends quietly, the worker is free for the next video
    video.refresh_from_db()
    assert video.status == Video.Status.FAILED and video.error == "ukončeno ručně" and video.task_token != "t"
    assert not tasks.cancel(video)  # nothing left to stop


def test_failure_of_a_stopped_task_does_not_touch_the_restarted_video(climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s", task_token="t")

    def download(*args, **kwargs):
        tasks.cancel(Video.objects.get(pk=video.pk))
        Video.objects.filter(pk=video.pk).update(status=Video.Status.QUEUED, task_token="new")  # sent again
        raise RuntimeError("HTTP 403")

    with mock.patch("pipeline.download.download", side_effect=download), pytest.raises(RuntimeError):
        tasks.process_video.fn(video.pk, "t")
    assert Video.objects.get(pk=video.pk).status == Video.Status.QUEUED


def test_process_video_time_limit_is_recorded(climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s")
    exc = dramatiq.middleware.TimeLimitExceeded()
    with mock.patch("pipeline.download.download", side_effect=exc), pytest.raises(type(exc)):
        tasks.process_video.fn(video.pk)
    video.refresh_from_db()
    assert video.status == Video.Status.FAILED


def test_command_process_video(climb_gpx, capsys):
    a = Video.objects.create(route=make_route(climb_gpx), source_id="aaaaaaaaaaa")
    b = Video.objects.create(route=make_route(climb_gpx), source_id="bbbbbbbbbbb", status=Video.Status.READY)
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        call_command("process_video", "--pending")
        call_command("process_video", str(b.pk))
    assert [c.kwargs["args"][0] for c in send.call_args_list] == [a.pk, b.pk]
    with pytest.raises(CommandError):
        call_command("process_video", "999")


def test_admin_video_detail_shows_progress_quality_and_process_button(admin, climb_gpx):
    route = make_route(climb_gpx)
    video = Video.objects.create(route=route, source_id="4Mmx8soDJ6s", status=Video.Status.READY)
    video.quality = {"method": "dp", "turn_corr": 0.35, "start_m": 85255.0, "end_m": 120300.0, "foo": 1}
    video.save()
    html = admin.get(reverse("admin:routes_video_change", args=[video.pk])).content.decode()
    assert "korelace zatáček" in html and "✗ špatné" in html and "km 85.25 – 120.30" in html and "foo=1" in html
    assert 'name="_process"' in html and "<svg" in html and 'http-equiv="refresh"' not in html
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        data = {"source": "youtube", "source_id": "4Mmx8soDJ6s", "data_source_id": "", "grade_source": "gpx"}
        r = admin.post(reverse("admin:routes_video_change", args=[video.pk]), {**data, "_process": "1"}, follow=True)
    assert send.call_count == 1 and "Odesláno ke zpracování" in r.content.decode()
    html = r.content.decode()
    assert "čeká na worker" in html and 'http-equiv="refresh" content="10"' in html


def test_admin_progress_text_while_processing(admin, climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s", status=Video.Status.PROCESSING)
    video.progress = {"step": "vizuální odometrie", "pct": 25.0, "since": time.time() - 60}
    video.save()
    html = admin.get(reverse("admin:routes_video_changelist")).content.decode()
    assert "vizuální odometrie 25 % · zbývá ~3 min" in html and 'http-equiv="refresh"' in html
    html = admin.get(reverse("admin:routes_route_changelist")).content.decode()
    assert "vizuální odometrie 25 %" in html and ">video<" in html


def test_admin_index_lists_videos_first(admin):
    html = admin.get(reverse("admin:index")).content.decode()
    assert html.index("/admin/routes/video/") < html.index("/admin/routes/route/")


# ---------- SPA ----------


def test_spa_fallback_and_assets(client, settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=app></div>")
    (dist / "assets" / "maplibre-gl-worker-abc.mjs").write_text("export {}")
    settings.FRONTEND_DIST = dist
    settings.WHITENOISE_ROOT = dist
    r = client.get("/ride/3")
    assert r.status_code == 200 and b"id=app" in r.content
    assert client.get("/").content == r.content
    worker = client.get("/assets/maplibre-gl-worker-abc.mjs")
    assert worker.status_code == 200
    assert worker["Content-Type"].startswith("text/javascript")  # module workers refuse other types
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/nope/").status_code == 404
    assert client.get("/admin").status_code == 301


def test_admin_route_preview_shows_profile_and_links(admin, climb_gpx, settings):
    settings.FRONTEND_URL = "http://localhost:5173"
    route = make_route(climb_gpx)
    html = admin.get(reverse("admin:routes_route_change", args=[route.pk])).content.decode()
    assert "<svg" in html and "#ed8936" in html  # 5 % climb band
    assert f"http://localhost:5173/check/{route.pk}" in html
    listing = admin.get(reverse("admin:routes_route_changelist")).content.decode()
    assert f"http://localhost:5173/check/{route.pk}" in listing


@pytest.mark.parametrize("model", ["video", "route"])
def test_admin_action_sends_videos_to_processing(admin, climb_gpx, model):
    new = Video.objects.create(route=make_route(climb_gpx), source_id="aaaaaaaaaaa")
    busy = Video.objects.create(route=make_route(climb_gpx), source_id="bbbbbbbbbbb", status=Video.Status.PROCESSING)
    ids = [new.pk, busy.pk] if model == "video" else [new.route_id, busy.route_id]
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        r = admin.post(
            reverse(f"admin:routes_{model}_changelist"),
            {"action": "process", "_selected_action": ids},
            follow=True,
        )
    assert [c.kwargs["args"][0] for c in send.call_args_list] == [new.pk]
    html = r.content.decode()
    assert "Odesláno ke zpracování" in html and "přeskočeno" in html


@pytest.mark.parametrize("model", ["video", "route"])
def test_admin_actions_stop_and_restart_a_stuck_video(admin, climb_gpx, model):
    stuck = Video.objects.create(
        route=make_route(climb_gpx), source_id="aaaaaaaaaaa", status=Video.Status.PROCESSING, task_token="dead"
    )
    ids = [stuck.pk if model == "video" else stuck.route_id]
    url = reverse(f"admin:routes_{model}_changelist")
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        r = admin.post(url, {"action": "restart", "_selected_action": ids}, follow=True)
    assert [c.kwargs["args"][0] for c in send.call_args_list] == [stuck.pk]
    assert "Odesláno ke zpracování" in r.content.decode()
    stuck.refresh_from_db()
    assert stuck.status == Video.Status.QUEUED and stuck.task_token not in ("dead", "")
    r = admin.post(url, {"action": "stop", "_selected_action": ids}, follow=True)
    assert "Ukončeno" in r.content.decode()
    assert Video.objects.get(pk=stuck.pk).status == Video.Status.FAILED


def test_admin_stop_button_on_the_video_detail(admin, climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="aaaaaaaaaaa", status=Video.Status.PROCESSING)
    url = reverse("admin:routes_video_change", args=[video.pk])
    assert 'name="_stop"' in admin.get(url).content.decode()
    data = {"source": "youtube", "source_id": video.source_id, "data_source_id": "", "grade_source": "gpx"}
    r = admin.post(url, {**data, "_stop": "1"}, follow=True)
    assert "Ukončeno" in r.content.decode() and 'name="_stop"' not in r.content.decode()
    assert Video.objects.get(pk=video.pk).status == Video.Status.FAILED


def test_quality_rows_overlay():
    from routes.display import quality_rows

    rows = {label: (value, v) for label, value, v in quality_rows({"cuts_s": [544, 1742], "elev_source": "elev"})}
    assert rows["střihy ve videu (čas)"][0] == "9:04, 29:02"
    assert rows["výška z"][0] == "výškoměru v overlayi"


def test_overlay_coverage_verdict_counts_only_the_fields_used():
    from routes.display import quality_rows, worst_verdict

    cov = {"speed": 0.998, "dist": 0.988, "elev": 0.999, "grade": 0.606}
    q = {"method": "overlay", "coverage": cov, "elev_source": "elev"}
    assert dict((label, v) for label, _, v in quality_rows(q))["přečteno z overlaye"] == "good"
    assert worst_verdict({**q, "elev_source": "grade"}) == "bad"  # elevation integrated from the poorly read grade


def test_superseded_task_is_skipped(climb_gpx):
    video = Video.objects.create(route=make_route(climb_gpx), source_id="4Mmx8soDJ6s", task_token="new")
    with mock.patch("pipeline.download.download") as dl:
        tasks.process_video.fn(video.pk, "old")
        tasks.process_video.fn(video.pk)  # message from before tokens existed
    dl.assert_not_called()
    assert Video.objects.get(pk=video.pk).status == Video.Status.NEW


def test_requeue_stuck_sends_active_videos_again(climb_gpx):
    stuck = Video.objects.create(
        route=make_route(climb_gpx), source_id="aaaaaaaaaaa", status=Video.Status.PROCESSING, task_token="old"
    )
    waiting = Video.objects.create(route=make_route(climb_gpx), source_id="bbbbbbbbbbb", status=Video.Status.QUEUED)
    Video.objects.create(route=make_route(climb_gpx), source_id="ccccccccccc", status=Video.Status.READY)
    with mock.patch.object(tasks.process_video, "send_with_options") as send:
        call_command("requeue_stuck")
    assert sorted(c.kwargs["args"][0] for c in send.call_args_list) == [stuck.pk, waiting.pk]
    stuck.refresh_from_db()
    assert stuck.status == Video.Status.QUEUED and stuck.task_token != "old"
