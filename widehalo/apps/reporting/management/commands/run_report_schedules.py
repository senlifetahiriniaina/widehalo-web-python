from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.reporting.services.scheduling import run_due_schedules


class Command(BaseCommand):
    help = (
        "Execute les RptSchedule dont next_run_at est echue (RPT-7). "
        "Planifiee quotidiennement (06h) par le registre des traitements "
        "periodiques ; reste appelable a la main."
    )

    def handle(self, *args, **options) -> None:
        count = run_due_schedules()
        self.stdout.write(self.style.SUCCESS(f"{count} planification(s) executee(s)."))
