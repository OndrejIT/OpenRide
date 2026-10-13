from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.http import Http404, HttpResponse
from rest_framework import viewsets

from routes.models import Route, Video
from routes.serializers import RouteDetailSerializer, RouteSerializer


class RouteViewSet(viewsets.ReadOnlyModelViewSet):
    """Rideable routes only: a profile exists and the video (if any) is processed."""

    def get_queryset(self):
        qs = (
            Route.objects.filter(profile__isnull=False)
            .filter(Q(video__isnull=True) | Q(video__status=Video.Status.READY))
            .select_related("video")
        )
        if self.action == "list":
            qs = qs.defer("profile", "segment", "gpx", "video__timing", "video__quality")
        return qs

    def get_serializer_class(self):
        return RouteSerializer if self.action == "list" else RouteDetailSerializer


def spa_index(request):
    """Client-side routes of the built frontend all load its index.html."""
    index = Path(settings.FRONTEND_DIST) / "index.html"
    if not index.is_file():
        raise Http404("Frontend není sestavený (bun run build)")
    return HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
