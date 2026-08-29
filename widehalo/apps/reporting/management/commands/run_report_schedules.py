from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.reporting.services.scheduling import run_due_schedules


class Command(BaseCommand):
    help = (
        "Execute les RptSchedule dont next_run_at est echue (RPT-7). "
        "Pas de cron auto-enregistre — a invoquer periodiquement par "
        "l'ordonnanceur systeme (ex. cron externe)."
    )

    def handle(self, *args, **options) -> None:
        count = run_due_schedules()
        self.stdout.write(self.style.SUCCESS(f"{count} planification(s) executee(s)."))
