from django.core.management.base import BaseCommand, CommandError

from routes.models import Video
from routes.tasks import enqueue


class Command(BaseCommand):
    help = "Odešle zpracování videa do fronty (Dramatiq)."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("video_id", nargs="?", type=int)
        group.add_argument("--pending", action="store_true", help="všechna videa ve stavu new")

    def handle(self, video_id=None, pending=False, **options):
        if pending:
            videos = list(Video.objects.filter(status=Video.Status.NEW))
        else:
            try:
                videos = [Video.objects.get(pk=video_id)]
            except Video.DoesNotExist as e:
                raise CommandError(f"Video {video_id} neexistuje") from e
        for video in videos:
            enqueue(video)
            self.stdout.write(f"odesláno: video {video.pk} ({video}, {video.grade_source})")
        if not videos:
            self.stdout.write("žádná nová videa")
