"""Commande ops (§5.8, STK-2, sprint A1) : controle de coherence entre
`StkQuant` (materialise) et l'agregat des `StkMove` (source de verite) pour
tous les tenants. Meme structure que ses commandes soeurs (boucle `Tenant.objects.all()` +
`tenant_step`). Planifiee depuis L0-3 : la cadence (quotidienne, 01h) est
declaree dans `apps.stocks.services.scheduling_registration` et appliquee a
l'ordonnanceur par `manage.py sync_scheduled_commands`."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.stocks.services.consistency import quant_ledger_consistency_report


class Command(BaseCommand):
    help = (
        "STK-2 : compare, pour chaque StkQuant, la quantite materialisee a "
        "la quantite re-derivee de l'agregat des StkMove, pour tous les "
        "tenants."
    )

    def handle(self, *args, **options) -> None:
        total_anomalies = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                rows = quant_ledger_consistency_report(tenant)
            anomalies = [row for row in rows if row["anomaly"]]
            total_anomalies += len(anomalies)
            if not rows:
                self.stdout.write(
                    self.style.WARNING(f"Tenant {tenant.code} : aucun quant à contrôler.")
                )
                continue
            for row in anomalies:
                self.stdout.write(
                    self.style.ERROR(
                        f"Tenant {tenant.code} : quant {row['quant_id']} "
                        f"(variant={row['variant_id']}, emplacement={row['location_id']}) — "
                        f"enregistre={row['recorded_qty']} derive={row['derived_qty']} "
                        f"ecart={row['variance']}"
                    )
                )
            if not anomalies:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(rows)} quant(s) controle(s), aucune anomalie."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_anomalies} anomalie(s) detectee(s)."))
