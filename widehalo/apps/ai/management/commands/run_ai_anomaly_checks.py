"""Commande ops (AI3) : declenche `run_all_checks` pour tous les tenants.
Destinee a etre invoquee periodiquement par une tache externe (cron
systeme) — meme discipline exacte que `apps.sales.management.commands.
run_sales_recurrences`/`apps.purchase.management.commands.
run_purchase_reordering` : AUCUN mecanisme de cron n'est cable ici ni
ailleurs pour cette commande (aucun precedent de planification Django-Q2
auto-enregistree pour une commande de maintenance dans ce depot), seule
cette commande appelable existe — un ops humain ou un cron externe la
declenche."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai.services.anomaly_detection import run_all_checks
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    help = "AI3 : execute toutes les verifications d'anomalies enregistrees, pour tous les tenants."

    def handle(self, *args, **options) -> None:
        total_created = 0
        for tenant in Tenant.objects.all():
            with activate_tenant(tenant.id):
                created = run_all_checks(tenant)
            total_created += len(created)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(created)} anomalie(s) detectee(s)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_created} anomalie(s) detectee(s)."))
