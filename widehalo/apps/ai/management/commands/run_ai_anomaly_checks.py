"""Commande ops (AI3) : declenche `run_all_checks` pour tous les tenants.

Planifiee depuis L0-3 : la cadence (quotidienne, 04h) est declaree dans
`apps.ai.services.scheduling_registration` et appliquee a l'ordonnanceur par
`manage.py sync_scheduled_commands`. Reste appelable a la main.

La deduplication de L0-1 est le prealable de cette planification : sans elle,
chaque passage recreait l'anomalie et, au-dela d'un certain seuil de gravite,
relancait un appel LLM."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai.services.anomaly_detection import run_all_checks
from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step


class Command(BaseCommand):
    help = "AI3 : execute toutes les verifications d'anomalies enregistrees, pour tous les tenants."

    def handle(self, *args, **options) -> None:
        total_created = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                created = run_all_checks(tenant)
            total_created += len(created)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(created)} anomalie(s) detectee(s)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_created} anomalie(s) detectee(s)."))
