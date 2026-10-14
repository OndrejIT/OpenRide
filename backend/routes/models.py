from django.core.exceptions import ValidationError
from django.db import models


class Route(models.Model):
    title = models.CharField("název", max_length=200)
    gpx = models.FileField("GPX", upload_to="gpx/", blank=True)
    # {"step_m": 10, "dist": [m], "elev": [m], "grade": [%], "lat": [], "lon": []}; lat/lon only with GPX
    profile = models.JSONField("profil", null=True, blank=True, editable=False)
    distance_km = models.FloatField("délka [km]", null=True, blank=True, editable=False)
    elev_gain_m = models.FloatField("stoupání [m]", null=True, blank=True, editable=False)
    elev_loss_m = models.FloatField("klesání [m]", null=True, blank=True, editable=False)
    max_grade = models.FloatField("max. sklon [%]", null=True, blank=True, editable=False)
    segment = models.JSONField("geometrie", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "trasa"
        verbose_name_plural = "trasy"
        ordering = ["title"]

    def __str__(self):
        return self.title


class Video(models.Model):
    class Source(models.TextChoices):
        YOUTUBE = "youtube", "YouTube"

    class GradeSource(models.TextChoices):
        GPX = "gpx", "GPX (napárování na video)"
        VIDEO = "video", "obraz (GeoCalib + SfM, pomalé)"
        OVERLAY = "overlay", "overlay ve videu (OCR rychlosti, km a výšky)"

    class Status(models.TextChoices):
        NEW = "new", "nové"
        QUEUED = "queued", "ve frontě"
        PROCESSING = "processing", "zpracovává se"
        READY = "ready", "hotovo"
        FAILED = "failed", "chyba"

    route = models.OneToOneField(Route, on_delete=models.CASCADE, related_name="video", verbose_name="trasa")
    source = models.CharField("zdroj", max_length=16, choices=Source, default=Source.YOUTUBE)
    source_id = models.CharField("ID videa", max_length=64)  # the played video
    # other upload of the same ride the data is read from (e.g. the one with the bike computer overlay)
    data_source_id = models.CharField("ID videa pro zpracování", max_length=64, blank=True)
    duration_s = models.IntegerField("délka [s]", null=True, blank=True, editable=False)
    grade_source = models.CharField("výpočet sklonu", max_length=8, choices=GradeSource, default=GradeSource.GPX)
    status = models.CharField("stav", max_length=16, choices=Status, default=Status.NEW, editable=False)
    error = models.TextField("chyba", blank=True, editable=False)
    # {"step": label, "pct": 0-100 within the step, "since": unix time the step started} while processing
    progress = models.JSONField("průběh", null=True, blank=True, editable=False)
    started_at = models.DateTimeField("začátek zpracování", null=True, blank=True, editable=False)
    # id of the last sent task; a message from an earlier send (requeued after a worker restart) is skipped
    task_token = models.CharField(max_length=32, blank=True, editable=False)
    finished_at = models.DateTimeField("konec zpracování", null=True, blank=True, editable=False)
    # {"t": [s], "dist": [m]} per video second: video time -> distance along Route.profile
    timing = models.JSONField("časování", null=True, blank=True, editable=False)
    quality = models.JSONField("kvalita napárování", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "video"
        verbose_name_plural = "videa"
        constraints = [models.UniqueConstraint(fields=["source", "source_id"], name="video_source_unique")]

    def __str__(self):
        return f"{self.get_source_display()} {self.source_id}"

    def clean(self):
        route = getattr(self, "route", None)
        if self.grade_source == self.GradeSource.GPX and route is not None and not route.gpx:
            raise ValidationError({"grade_source": "Výpočet z GPX vyžaduje GPX u trasy."})


class Ride(models.Model):
    """A ride on the trainer, saved by the rider once finished: per-second samples and their summary."""

    route = models.ForeignKey(
        Route, on_delete=models.SET_NULL, null=True, blank=True, related_name="rides", verbose_name="trasa"
    )
    title = models.CharField("trasa (název při jízdě)", max_length=200)
    started_at = models.DateTimeField("začátek")
    created_at = models.DateTimeField("uloženo", auto_now_add=True)
    duration_s = models.IntegerField("doba jízdy [s]")
    distance_m = models.FloatField("vzdálenost [m]")
    elev_gain_m = models.FloatField("stoupání [m]")
    avg_power = models.FloatField("průměrný výkon [W]", null=True, blank=True)
    max_power = models.FloatField("max. výkon [W]", null=True, blank=True)
    avg_rpm = models.FloatField("průměrná kadence", null=True, blank=True)
    avg_pulse = models.FloatField("průměrný tep", null=True, blank=True)
    max_pulse = models.FloatField("max. tep", null=True, blank=True)
    # {"t": [s], "dist": [m], "elev": [m], "grade": [%], "sim": [%], "brake": [], "power": [W], "rpm": [], "pulse": []}
    # one sample per ridden second; trainer values are null while the trainer is not connected
    samples = models.JSONField("záznam")

    class Meta:
        verbose_name = "jízda"
        verbose_name_plural = "jízdy"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.title} {self.started_at:%Y-%m-%d %H:%M}"
