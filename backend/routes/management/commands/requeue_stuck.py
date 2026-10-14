from django.core.management.base import BaseCommand

from routes.models import Video
from routes.tasks import ACTIVE, enqueue


class Command(BaseCommand):
    help = "Znovu odešle videa, která visí ve frontě nebo při zpracování (spouští se při startu workeru)."

    def handle(self, **options):
        # at worker start nothing is being processed, so these lost their task (restart, emptied Redis);
        # the new token makes a surviving old message skip itself
        for video in Video.objects.filter(status__in=ACTIVE).order_by("pk"):  # keep the original queue order
            enqueue(video)
            self.stdout.write(f"znovu odesláno: video {video.pk} ({video})")
