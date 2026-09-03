"""Commande ops (cahier Phase 2 §12) : rafraîchit l'entrepôt en étoile pour
tous les tenants. Destinée à être invoquée périodiquement par une tâche
externe (cron système) — aucun mécanisme de planification récurrente
Django-Q2 n'est câblé ailleurs dans le projet (cf. `apps.core.tasks`),
même discipline que `run_sales_recurrences`/`run_purchase_reordering`."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.analytics.models import AnRefreshRun
from apps.analytics.services.refresh import refresh_warehouse_for_tenant
from apps.core.models.tenant import Tenant


class Command(BaseCommand):
    help = "Rafraîchit l'entrepôt en étoile analytique (dimensions + faits) pour tous les tenants."

    def handle(self, *args, **options) -> None:
        for tenant in Tenant.objects.all():
            try:
                run = refresh_warehouse_for_tenant(tenant, triggered_by=AnRefreshRun.TRIGGER_CRON)
            except Exception as exc:  # noqa: BLE001 - un tenant en echec ne doit jamais bloquer les suivants
                self.stdout.write(
                    self.style.ERROR(f"Tenant {tenant.code} : échec du rafraîchissement ({exc}).")
                )
                continue
            if run.status == AnRefreshRun.STATUS_SUCCESS:
                reconciliation = (
                    "OK"
                    if run.reconciliation_ok
                    else ("ÉCART" if run.reconciliation_ok is False else "non contrôlé")
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {run.rows_processed} ligne(s) traitée(s), "
                        f"réconciliation {reconciliation}."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"Tenant {tenant.code} : {run.error_message}")
                )
