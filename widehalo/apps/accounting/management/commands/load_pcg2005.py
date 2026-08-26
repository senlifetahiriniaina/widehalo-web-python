from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.accounting.services.chart_of_accounts import load_pcg2005
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    help = (
        "Charge le plan comptable PCG 2005 malgache (jeu de donnees simplifie, "
        "non valide par un expert-comptable OECFM) pour un tenant."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            created = load_pcg2005(tenant)
        self.stdout.write(self.style.SUCCESS(f"{created} compte(s) cree(s) pour {tenant.code}."))
