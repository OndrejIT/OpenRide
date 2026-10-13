from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework.routers import SimpleRouter

from routes.manage import ManageVideoViewSet, session
from routes.views import RouteViewSet, spa_index

router = SimpleRouter()
router.register("routes", RouteViewSet, basename="route")
router.register("manage/videos", ManageVideoViewSet, basename="manage-video")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/manage/session/", session),
    path("api/", include(router.urls)),
    # everything else is a frontend route; unknown /api/ and /admin paths must stay real 404s/redirects
    re_path(r"^(?!(?:api|admin|static|media|assets)(?:/|$)).*$", spa_index),
]
