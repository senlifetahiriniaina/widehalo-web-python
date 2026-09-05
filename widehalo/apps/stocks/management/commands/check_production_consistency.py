"""Commande ops (§5.8, ST6, RG-STK-6) : controle de coherence
production/stock pour tous les tenants et affiche les anomalies detectees.
Meme structure que ses commandes soeurs (boucle `Tenant.objects.all()` +
`tenant_step`). Planifiee depuis L0-3 : la cadence (hebdomadaire, 01h) est
declaree dans `apps.stocks.services.scheduling_registration` et appliquee a
l'ordonnanceur par `manage.py sync_scheduled_commands`."""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.stocks.services.consistency import DEFAULT_WINDOW_DAYS, production_consistency_report


class Command(BaseCommand):
    help = (
        "RG-STK-6 : compare, pour chaque ordre de fabrication cloture des "
        f"les {DEFAULT_WINDOW_DAYS} derniers jours (parametrable), la "
        "quantite declaree produite a la quantite reellement entree en "
        "stock, pour tous les tenants."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--window-days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help="Fenetre (en jours) de recherche des ordres de fabrication clotures.",
        )

    def handle(self, *args, **options) -> None:
        window_days = options["window_days"]
        since = timezone.now().date() - dt.timedelta(days=window_days)

        total_anomalies = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                rows = production_consistency_report(tenant, since=since)
            anomalies = [row for row in rows if row["anomaly"]]
            total_anomalies += len(anomalies)
            if not rows:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.code} : aucun ordre de fabrication cloture sur la periode."
                    )
                )
                continue
            for row in anomalies:
                self.stdout.write(
                    self.style.ERROR(
                        f"Tenant {tenant.code} : OF {row['order_reference']} — "
                        f"declare={row['qty_declared']} entre_en_stock={row['qty_entered_stock']} "
                        f"ecart={row['variance']}"
                    )
                )
            if not anomalies:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(rows)} OF controle(s), aucune anomalie."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_anomalies} anomalie(s) detectee(s)."))
