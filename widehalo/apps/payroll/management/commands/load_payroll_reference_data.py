from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.payroll.services.seed import seed_payroll_regulatory_params
from apps.payroll.services.structures import load_madagascar_structure


class Command(BaseCommand):
    help = (
        "Charge les parametres reglementaires §5.10.3 (IRSA/CNaPS/OSTIE/SME, "
        "non valides OECFM) et la structure salariale de reference Madagascar "
        "(PAY-M5, fixture modifiable) pour un tenant."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            created_params = seed_payroll_regulatory_params(tenant)
            structure = load_madagascar_structure(tenant)
        self.stdout.write(
            self.style.SUCCESS(
                f"{created_params} parametre(s) reglementaire(s) cree(s), "
                f"structure '{structure.code}' chargee pour {tenant.code}."
            )
        )
