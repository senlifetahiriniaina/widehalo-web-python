from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.core.events import dispatch_event
from apps.core.models.event import EventLog


class Command(BaseCommand):
    help = "Rejoue les evenements en echec (status=failed) — utile en exploitation."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--event-type", default=None)

    def handle(self, *args, **options) -> None:
        queryset = EventLog.objects.filter(status=EventLog.STATUS_FAILED)
        if options["event_type"]:
            queryset = queryset.filter(event_type=options["event_type"])

        count = 0
        for event in queryset:
            event.attempts = 0
            event.save(update_fields=["attempts"])
            dispatch_event(str(event.id))
            count += 1

        self.stdout.write(self.style.SUCCESS(f"{count} évènement(s) rejoué(s)."))
