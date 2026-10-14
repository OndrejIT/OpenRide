from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from routes import services, tasks
from routes.display import duration_text, profile_svg, progress_text, quality_table
from routes.forms import RouteForm, VideoAddForm, VideoForm
from routes.models import Ride, Route, Video

ACTIVE = tasks.ACTIVE


class VideoFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        has_video = any(f.cleaned_data and not f.cleaned_data.get("DELETE") for f in self.forms)
        if not has_video and not self.instance.gpx:
            raise ValidationError("Trasa bez videa (virtuální průlet) vyžaduje GPX.")


def preview_html(route: Route):
    if not route.pk or not route.profile:
        return "—"
    base = settings.FRONTEND_URL
    links = format_html(
        '<p><a href="{}/check/{}" target="_blank">kontrola napárování</a> · '
        '<a href="{}/ride/{}" target="_blank">trenažér</a></p>',
        base,
        route.pk,
        base,
        route.pk,
    )
    return mark_safe(profile_svg(route.profile)) + links  # SVG built from numbers only


def check_link_html(route: Route):
    if not route.profile:
        return "—"
    return format_html('<a href="{}/check/{}" target="_blank">kontrola</a>', settings.FRONTEND_URL, route.pk)


def youtube_html(video: Video):
    """Links to the played video and, when it differs, the processed upload."""
    links = [(video.source_id, "")]
    if video.data_source_id and video.data_source_id != video.source_id:
        links.append((video.data_source_id, " (zpracovávané)"))
    return format_html_join(
        " · ",
        '<a href="https://www.youtube.com/watch?v={}" target="_blank" rel="noopener">▶ {}</a>{}',
        ((i, i, note) for i, note in links),
    )


def video_link(video: Video):
    url = reverse("admin:routes_video_change", args=[video.pk])
    return format_html('<a href="{}">{}</a>', url, video)


class VideoInline(admin.StackedInline):
    model = Video
    form = VideoForm
    formset = VideoFormSet
    extra = 0
    max_num = 1
    fields = ["detail", "youtube", "source", "source_id", "data_source_id", "grade_source", "state"]
    readonly_fields = ["detail", "youtube", "state"]

    @admin.display(description="detail")
    def detail(self, obj):
        return video_link(obj) if obj.pk else "—"

    @admin.display(description="YouTube")
    def youtube(self, obj):
        return youtube_html(obj) if obj.pk else "—"

    @admin.display(description="stav")
    def state(self, obj):
        return progress_text(obj) if obj.pk else "—"


def enqueue_videos(modeladmin, request, videos) -> None:
    """Send videos to the worker; one already queued or being processed is skipped (it would run twice)."""
    busy = [v for v in videos if v.status in ACTIVE]
    sent = [v for v in videos if v.status not in ACTIVE]
    for video in sent:
        tasks.enqueue(video)
    if sent:
        modeladmin.message_user(request, f"Odesláno ke zpracování: {', '.join(str(v) for v in sent)}", messages.SUCCESS)
    if busy:
        modeladmin.message_user(
            request,
            f"Už je ve frontě nebo se zpracovává, přeskočeno: {', '.join(str(v) for v in busy)}",
            messages.WARNING,
        )
    if not videos:
        modeladmin.message_user(request, "Vybrané trasy nemají video.", messages.WARNING)


def cancel_videos(modeladmin, request, videos) -> None:
    stopped = [v for v in videos if tasks.cancel(v)]
    if stopped:
        modeladmin.message_user(request, f"Ukončeno: {', '.join(str(v) for v in stopped)}", messages.SUCCESS)
    else:
        modeladmin.message_user(request, "Nic z vybraného nečeká ve frontě ani se nezpracovává.", messages.WARNING)


class ProcessingAdminMixin:
    """Processing actions, auto-refresh while something is processing and process/stop buttons on the change form."""

    REFRESH_S = 10
    actions = ["process", "stop", "restart"]

    @admin.action(description="Zpracovat")
    def process(self, request, queryset):
        enqueue_videos(self, request, self.selected_videos(queryset))

    @admin.action(description="Ukončit zpracování")
    def stop(self, request, queryset):
        cancel_videos(self, request, self.selected_videos(queryset))

    # for a video stuck as processing (worker or database crashed) and to restart with changed settings
    @admin.action(description="Ukončit a zpracovat znovu")
    def restart(self, request, queryset):
        videos = self.selected_videos(queryset)
        for video in videos:
            tasks.cancel(video)
            video.refresh_from_db()
        enqueue_videos(self, request, videos)

    def changelist_view(self, request, extra_context=None):
        active = Video.objects.filter(status__in=ACTIVE).exists()
        return super().changelist_view(request, {**(extra_context or {}), "refresh_s": active and self.REFRESH_S})

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        video = self.video_of(self.get_object(request, object_id)) if object_id else None
        context = {
            **(extra_context or {}),
            "show_process": self.model is Video or video is not None,
            "show_stop": video is not None and video.status in ACTIVE,
            # a page left open shows the progress; nobody edits a video while it is being processed
            "refresh_s": video is not None and video.status in ACTIVE and self.REFRESH_S,
        }
        return super().changeform_view(request, object_id, form_url, context)

    def _process_redirect(self, request, obj):
        video = self.video_of(obj)
        if video is None:
            self.message_user(request, "Trasa nemá video.", messages.WARNING)
        else:
            video.refresh_from_db()
            enqueue_videos(self, request, [video])
        return HttpResponseRedirect(reverse(f"admin:routes_{self.model._meta.model_name}_change", args=[obj.pk]))

    def response_change(self, request, obj):
        if "_process" in request.POST:
            return self._process_redirect(request, obj)
        if "_stop" in request.POST and (video := self.video_of(obj)) is not None:
            cancel_videos(self, request, [video])
            return HttpResponseRedirect(reverse(f"admin:routes_{self.model._meta.model_name}_change", args=[obj.pk]))
        return super().response_change(request, obj)

    def response_add(self, request, obj, post_url_continue=None):
        if "_process" in request.POST:
            return self._process_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)


@admin.register(Video)
class VideoAdmin(ProcessingAdminMixin, admin.ModelAdmin):
    form = VideoForm
    list_display = ["route_title", "youtube", "grade_source", "state", "check_link"]
    list_display_links = ["route_title"]
    list_filter = ["status", "grade_source"]
    readonly_fields = ["route_link", "youtube", "state", "error", "duration_s", "quality_view", "preview"]
    add_fieldsets = [
        (
            None,
            {
                "description": "Vlož URL videa z YouTube; trasa se založí sama s názvem videa. "
                "GPX přidej, pokud ho máš: dá mapu a 3D průlet a umožní výpočet sklonu z GPX.",
                "fields": ["source", "source_id", "data_source_id", "grade_source", "gpx"],
            },
        )
    ]
    change_fieldsets = [
        (None, {"fields": ["route_link", "youtube", "source", "source_id", "data_source_id", "grade_source"]}),
        ("Zpracování", {"fields": ["state", "error", "quality_view"]}),
        ("Výsledek", {"fields": ["duration_s", "preview"]}),
    ]

    @staticmethod
    def video_of(obj):
        return obj

    @staticmethod
    def selected_videos(queryset):
        return list(queryset)

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = VideoAddForm if obj is None else VideoForm
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        return self.change_fieldsets if obj else self.add_fieldsets

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else []

    @admin.display(description="trasa", ordering="route__title")
    def route_title(self, obj):
        return obj.route.title

    @admin.display(description="trasa")
    def route_link(self, obj):
        url = reverse("admin:routes_route_change", args=[obj.route_id])
        return format_html('<a href="{}">{}</a>', url, obj.route.title)

    @admin.display(description="YouTube", ordering="source_id")
    def youtube(self, obj):
        return youtube_html(obj)

    @admin.display(description="stav", ordering="status")
    def state(self, obj):
        return progress_text(obj)

    @admin.display(description="kvalita výsledku")
    def quality_view(self, obj):
        return quality_table(obj.quality)

    @admin.display(description="náhled")
    def preview(self, obj):
        return preview_html(obj.route)

    @admin.display(description="kontrola")
    def check_link(self, obj):
        return check_link_html(obj.route)

    def get_queryset(self, request):
        # the profile is needed for the preview and the check link; only the per-second timing is big and unused here
        return super().get_queryset(request).select_related("route").defer("timing", "route__segment")

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
        else:
            form.save_with_route()  # saves `obj` itself: it is the form's instance


@admin.register(Route)
class RouteAdmin(ProcessingAdminMixin, admin.ModelAdmin):
    form = RouteForm
    inlines = [VideoInline]
    list_display = ["title", "kind", "distance_km", "elev_gain_m", "max_grade", "video_state", "check_link"]
    readonly_fields = ["distance_km", "elev_gain_m", "elev_loss_m", "max_grade", "preview"]
    search_fields = ["title"]

    @staticmethod
    def video_of(obj):
        return getattr(obj, "video", None) if obj is not None else None

    def get_inlines(self, request, obj):
        return [VideoInline] if obj else []  # a new route here has no video (Videa → Přidat creates both)

    def get_fieldsets(self, request, obj=None):
        if obj:
            return super().get_fieldsets(request, obj)
        description = "Trasa bez videa: virtuální průlet z GPX. Video přidávej ve Videa → Přidat."
        return [(None, {"description": description, "fields": ["title", "gpx"]})]

    @staticmethod
    def selected_videos(queryset):
        return list(Video.objects.filter(route__in=queryset))

    @admin.display(description="typ")
    def kind(self, obj):
        return "video" if self.video_of(obj) else "virtuální"

    @admin.display(description="kontrola")
    def check_link(self, obj):
        return check_link_html(obj)

    @admin.display(description="náhled")
    def preview(self, obj):
        return preview_html(obj)

    @admin.display(description="video")
    def video_state(self, obj):
        video = self.video_of(obj)
        return format_html("{} · {}", video_link(video), progress_text(video)) if video else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("video").defer("segment", "video__timing")

    def save_model(self, request, obj, form, change):
        if "gpx" in form.changed_data and not obj.gpx:
            obj.profile = obj.segment = None
            obj.distance_km = obj.elev_gain_m = obj.elev_loss_m = obj.max_grade = None
        super().save_model(request, obj, form, change)
        if "gpx" in form.changed_data and obj.gpx:
            services.apply_gpx(obj)  # reads the stored file, so only after the save
            obj.save()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if change and "gpx" in form.changed_data:
            # the old alignment refers to the previous GPX; the video has to be processed again
            Video.objects.filter(route=form.instance).exclude(status=Video.Status.NEW).update(
                status=Video.Status.NEW, timing=None, quality=None, error=""
            )


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ["title", "started_at", "duration", "distance_km", "elev_gain_m", "avg_power", "avg_rpm"]
    list_filter = ["route"]
    exclude = ["samples"]  # thousands of numbers; shown in the app's ride history

    def has_add_permission(self, request):
        return False  # rides come from the trainer

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="doba", ordering="duration_s")
    def duration(self, obj):
        return duration_text(obj.duration_s)

    @admin.display(description="km", ordering="distance_m")
    def distance_km(self, obj):
        return round(obj.distance_m / 1000, 2)
