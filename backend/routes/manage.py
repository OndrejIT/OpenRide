"""Management API for the dashboard: videos with their processing state, adding them, sending them to processing
and stopping it.

Staff only, through the Django session (log in at /admin/login/); the forms are the admin's, so validation is shared.
"""

from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

from routes import tasks
from routes.display import progress_text, quality_rows, worst_verdict
from routes.forms import VideoAddForm
from routes.models import Video

TRUE = ("1", "true", "on")


def video_json(v: Video) -> dict:
    return {
        "id": v.pk,
        "route_id": v.route_id,
        "title": v.route.title,
        "source_id": v.source_id,
        "data_source_id": v.data_source_id,
        "grade_source": v.grade_source,
        "grade_source_label": v.get_grade_source_display(),
        "has_gpx": bool(v.route.gpx),
        "status": v.status,
        "status_label": v.get_status_display(),
        "state": progress_text(v),
        "progress": v.progress,
        "error": v.error,
        "duration_s": v.duration_s,
        "quality": [
            {"label": label, "value": value, "verdict": verdict}
            for label, value, verdict in quality_rows(v.quality or {})
        ],
        "verdict": worst_verdict(v.quality),
        "started_at": v.started_at,
        "finished_at": v.finished_at,
        "admin_url": reverse("admin:routes_video_change", args=[v.pk]),
    }


def videos():
    # the per-second timing and the route geometry are big and not shown on the dashboard
    return Video.objects.select_related("route").defer("timing", "route__profile", "route__segment")


class ManageVideoViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def list(self, request):
        return Response([video_json(v) for v in videos().order_by("-pk")])

    def create(self, request):
        data = request.data.copy()
        data.setdefault("source", Video.Source.YOUTUBE)  # the only source; a hidden field in the admin
        form = VideoAddForm(data, request.FILES)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        video = form.save_with_route()
        if str(request.data.get("process", "")).lower() in TRUE:
            tasks.enqueue(video)
        return Response(video_json(videos().get(pk=video.pk)), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        video = get_object_or_404(videos(), pk=pk)
        if video.status in tasks.ACTIVE:
            return Response({"detail": "Video už je ve frontě nebo se zpracovává."}, status=status.HTTP_409_CONFLICT)
        tasks.enqueue(video)
        return Response(video_json(videos().get(pk=video.pk)))

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        video = get_object_or_404(videos(), pk=pk)
        if not tasks.cancel(video):
            return Response({"detail": "Video nečeká ve frontě ani se nezpracovává."}, status=status.HTTP_409_CONFLICT)
        return Response(video_json(videos().get(pk=video.pk)))


@ensure_csrf_cookie  # the dashboard's POSTs need the token cookie even right after logging in elsewhere
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
def session(request):
    user = request.user
    return Response(
        {
            "user": user.get_username() if user and user.is_authenticated else None,
            "is_staff": bool(user and user.is_staff),
            "grade_sources": [{"value": v, "label": label} for v, label in Video.GradeSource.choices],
        }
    )
