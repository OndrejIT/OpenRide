"""Forms shared by the admin and the management API: one set of validation for adding videos."""

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from pipeline import gpx
from routes import services
from routes.models import Route, Video


def validate_gpx(f):
    if isinstance(f, UploadedFile):
        try:
            gpx.parse(f.read())
        except (ValueError, SyntaxError) as e:  # ParseError is a SyntaxError
            raise ValidationError(f"Neplatný GPX: {e}") from e
        finally:
            f.seek(0)
    return f


class RouteForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = ["title", "gpx"]

    def clean_gpx(self):
        f = validate_gpx(self.cleaned_data.get("gpx"))
        if self.instance.pk is None and not f:
            # a new route here is a virtual ride; videos are added under Videa
            raise ValidationError("Trasa bez videa (virtuální průlet) vyžaduje GPX. Video přidej ve Videa → Přidat.")
        return f


class VideoForm(forms.ModelForm):
    source_id = forms.CharField(label="URL videa", help_text="Video, které se přehrává: URL na YouTube (nebo ID)")
    data_source_id = forms.CharField(
        label="URL videa pro zpracování",
        required=False,
        help_text="Jiná verze stejné jízdy, ze které se data počítají (např. s overlayem cyklopočítače). "
        "Prázdné = zpracuje se přehrávané video. Časový posun mezi verzemi se určí automaticky.",
    )

    class Meta:
        model = Video
        fields = ["source", "source_id", "data_source_id", "grade_source"]
        widgets = {"source": forms.HiddenInput}  # YouTube only; kept in the form for the unique check

    @staticmethod
    def _youtube_id(value: str) -> str:
        try:
            return services.parse_youtube_id(value)
        except ValueError as e:
            raise ValidationError(str(e)) from e

    def clean_source_id(self):
        return self._youtube_id(self.cleaned_data["source_id"])

    def clean_data_source_id(self):
        value = self.cleaned_data["data_source_id"].strip()
        return self._youtube_id(value) if value else ""


class VideoAddForm(VideoForm):
    """The one place to add a video: its route is created with the title from YouTube and the optional GPX."""

    gpx = forms.FileField(
        label="GPX",
        required=False,
        help_text="Volitelné. Nutné pro výpočet sklonu z GPX; dá trase i mapu a 3D průlet.",
    )

    def clean_gpx(self):
        return validate_gpx(self.cleaned_data.get("gpx"))

    def clean(self):
        data = super().clean()
        if data.get("grade_source") == Video.GradeSource.GPX and not data.get("gpx") and "gpx" not in self.errors:
            self.add_error("gpx", "Výpočet z GPX vyžaduje GPX.")
        if data.get("source_id"):
            try:
                self.title = services.youtube_title(data["source_id"])
            except ValueError as e:
                self.add_error("source_id", str(e))
        return data

    def save_with_route(self) -> Video:
        """Create the route (title from YouTube, optional GPX with its profile) and the video in it."""
        route = Route.objects.create(title=self.title, gpx=self.cleaned_data["gpx"])
        if route.gpx:
            services.apply_gpx(route)  # reads the stored file, so only after the save
            route.save()
        video = self.save(commit=False)
        video.route = route
        video.save()
        return video
