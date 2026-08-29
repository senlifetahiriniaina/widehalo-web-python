from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.strategy.models import SECTOR_TEXTILE
from apps.strategy.services.benchmarks import create_sector_benchmark

_FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "textile_mg.json"


class Command(BaseCommand):
    help = (
        "Charge le referentiel de benchmarks sectoriels textile (jeu de "
        "donnees indicatif, NON valide par un expert sectoriel independant) "
        "pour un tenant."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")
        parser.add_argument(
            "--valid-from",
            default=None,
            help="Date d'effet (AAAA-MM-JJ), aujourd'hui par defaut.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        valid_from = (
            dt.date.fromisoformat(options["valid_from"])
            if options["valid_from"]
            else dt.date.today()
        )
        rows = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        created = 0
        with activate_tenant(tenant.id):
            for row in rows:
                create_sector_benchmark(
                    tenant,
                    sector_code=SECTOR_TEXTILE,
                    kpi_code=row["kpi_code"],
                    kpi_label=row["kpi_label"],
                    target_min=Decimal(row["target_min"]) if row.get("target_min") else None,
                    target_max=Decimal(row["target_max"]) if row.get("target_max") else None,
                    unit=row.get("unit", ""),
                    valid_from=valid_from,
                )
                created += 1
        self.stdout.write(
            self.style.SUCCESS(f"{created} benchmark(s) textile charge(s) pour {tenant.code}.")
        )
