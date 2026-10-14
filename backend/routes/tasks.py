import logging
import time
import traceback
import uuid
from pathlib import Path

import dramatiq
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from routes import services
from routes.models import Video

log = logging.getLogger(__name__)

# processing time per second of video, generous over measured runs (Docker on Apple Silicon CPU):
# overlay OCR 0.35 s/s, gpx VO + flow ~0.2 s/s, video GeoCalib + SfM several s/s
TIME_FACTOR = {Video.GradeSource.GPX: 2.0, Video.GradeSource.OVERLAY: 1.5, Video.GradeSource.VIDEO: 8.0}
MIN_TIME_LIMIT_S = 3600
# Dramatiq safety net only; the real limit follows the video length (unknown until downloaded)
HARD_TIME_LIMIT_MS = 24 * 3600 * 1000
PROGRESS_INTERVAL_S = 5.0
# sending such a video again would process it twice
ACTIVE = (Video.Status.QUEUED, Video.Status.PROCESSING)


class ProcessingTimeout(Exception):
    pass


class Cancelled(Exception):
    """The video was stopped (or sent again) from the admin while this task was running."""


class Progress:
    """report() callback: writes the current step to the video (throttled) and enforces the time limit."""

    def __init__(self, video_id: int, token: str = ""):
        self.video_id, self.token = video_id, token
        self.started = time.time()
        self.step, self.since, self.written = None, 0.0, 0.0
        self.deadline, self.limit_s = None, None

    def set_limit(self, limit_s: float) -> None:
        self.limit_s = limit_s
        self.deadline = self.started + limit_s

    def __call__(self, step: str, pct: float) -> None:
        now = time.time()
        if self.deadline and now > self.deadline:
            raise ProcessingTimeout(f"překročen časový limit {self.limit_s / 60:.0f} min")
        if step != self.step:
            self.step, self.since = step, now
        elif now - self.written < PROGRESS_INTERVAL_S:
            return
        self.written = now
        # a changed token = stopped from the admin: the task ends at its next report instead of running for hours
        if not self.mine().update(progress={"step": step, "pct": round(pct, 1), "since": round(self.since)}):
            raise Cancelled

    def mine(self):
        return Video.objects.filter(pk=self.video_id, task_token=self.token)


def time_limit_s(video: Video, duration_s: float) -> float:
    return max(MIN_TIME_LIMIT_S, TIME_FACTOR[video.grade_source] * duration_s)


@dramatiq.actor(max_retries=0, time_limit=HARD_TIME_LIMIT_MS)
def process_video(video_id: int, token: str | None = None) -> None:
    from pipeline.progress import reporting

    video = Video.objects.select_related("route").get(pk=video_id)
    # an older message (sent again after a worker restart, or from before tokens existed) must not run twice
    if video.task_token and token != video.task_token:
        log.info("video %s: skipping a superseded task", video_id)
        return
    progress = Progress(video_id, video.task_token)
    Video.objects.filter(pk=video_id).update(
        status=Video.Status.PROCESSING, error="", progress=None, started_at=timezone.now(), finished_at=None
    )
    try:
        with reporting(progress):
            run(video, progress)
    except Cancelled:
        log.info("video %s: stopped from the admin", video_id)
    except BaseException as e:  # TimeLimitExceeded is not an Exception; the video must not stay "processing"
        log.exception("video %s failed", video_id)
        message = "".join(traceback.format_exception_only(e)).strip()
        if connection.connection is not None and not connection.is_usable():
            connection.close()  # dead after a database restart; the next query opens a new one, so the state is saved
        progress.mine().update(
            status=Video.Status.FAILED,
            error=f"{progress.step}: {message}" if progress.step else message,
            progress=None,
            finished_at=timezone.now(),
        )
        raise


def enqueue(video: Video) -> None:
    previous = Video.objects.filter(pk=video.pk).values_list("status", flat=True).first()
    token = uuid.uuid4().hex
    # before sending: a fast worker would otherwise set "processing" first and get overwritten
    Video.objects.filter(pk=video.pk).update(status=Video.Status.QUEUED, error="", progress=None, task_token=token)
    try:
        process_video.send(video.pk, token)
    except Exception:
        Video.objects.filter(pk=video.pk).update(status=previous)
        raise


def cancel(video: Video) -> bool:
    """Stop a queued or running video; the new token makes its task end at the next progress report."""
    return bool(
        Video.objects.filter(pk=video.pk, status__in=ACTIVE).update(
            status=Video.Status.FAILED,
            error="ukončeno ručně",
            progress=None,
            finished_at=timezone.now(),
            task_token=uuid.uuid4().hex,
        )
    )


def run(video: Video, progress: Progress) -> None:
    from pipeline import process, vo
    from pipeline.download import download

    route = video.route
    data_id = video.data_source_id or video.source_id
    # cache keyed by the processed upload: changing the video in the admin never reuses stale results
    workdir = Path(settings.CACHE_DIR) / "videos" / data_id
    downloads = []
    try:
        path = download(data_id, workdir, name=data_id)
        downloads.append(path)
        fps, n, _, _ = vo.video_info(str(path))
        progress.set_limit(time_limit_s(video, n / fps))
        sync = None
        if data_id != video.source_id:
            # low resolution is enough for the motion signal; checked first so a mismatch fails before processing
            play = download(video.source_id, workdir, name=video.source_id, height=360)
            downloads.append(play)
            sync = process.sync_videos(path, play, workdir)
        if video.grade_source == Video.GradeSource.GPX:
            result = process.process_gpx(path, workdir, services.load_track(route))
        elif video.grade_source == Video.GradeSource.OVERLAY:
            result = process.process_overlay(path, workdir)
        else:
            result = process.process_video_grade(path, workdir, settings.VIDEO_ASSUMED_KMH)
        if sync:
            result = process.apply_sync(result, sync)
    finally:
        for p in downloads:
            p.unlink(missing_ok=True)  # big; the small intermediate results stay cached in workdir

    with transaction.atomic():
        services.set_profile(route, result["profile"])
        route.save()
        video.duration_s = result["duration_s"]
        video.timing = result["timing"]
        video.quality = result["quality"]
        video.status = Video.Status.READY
        video.error = ""
        video.progress = None
        video.finished_at = timezone.now()
        # not a full save: started_at was set by an update the in-memory object does not know
        video.save(update_fields=["duration_s", "timing", "quality", "status", "error", "progress", "finished_at"])
