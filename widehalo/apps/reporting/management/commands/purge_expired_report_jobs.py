from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.reporting.services.engine import purge_expired_jobs


class Command(BaseCommand):
    help = "Supprime les fichiers de RptJob expires (expires_at <= now, cf. RPT-6)."

    def handle(self, *args, **options) -> None:
        count = purge_expired_jobs()
        self.stdout.write(self.style.SUCCESS(f"{count} job(s) de rapport purge(s)."))
