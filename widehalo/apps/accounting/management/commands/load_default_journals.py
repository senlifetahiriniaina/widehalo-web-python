from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.accounting.services.chart_of_accounts import ensure_default_journals
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    help = (
        "Cree les 7 journaux comptables par defaut (ventes, achats, banque, caisse, "
        "operations diverses, paie, stock) pour un tenant. Idempotent."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            created = ensure_default_journals(tenant)
        self.stdout.write(
            self.style.SUCCESS(f"{created} journal/journaux cree(s) pour {tenant.code}.")
        )
