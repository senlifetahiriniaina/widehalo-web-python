"""Commande ops (cahier Phase 2 §12) : rafraîchit l'entrepôt en étoile pour
tous les tenants.

Planifiée depuis L0-3 : la cadence (quotidienne, 01h) est déclarée dans
`apps.analytics.services.scheduling_registration` et appliquée à
l'ordonnanceur par `manage.py sync_scheduled_commands`. Reste appelable à la
main.

C'est la commande dont l'absence de planification coûtait le plus cher : sans
rafraîchissement, les modules BI, Forecast et Strategy restituaient des
tableaux vides en exploitation alors que chacun passait ses tests."""

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
                self.stdout.write(self.style.WARNING(f"Tenant {tenant.code} : {run.error_message}"))
