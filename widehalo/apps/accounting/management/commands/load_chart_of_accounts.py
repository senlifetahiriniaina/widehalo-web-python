from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.accounting.services.chart_of_accounts import load_chart_of_accounts
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    """D10-5 — charge le plan de comptes du referentiel actif du tenant.

    Remplace `load_pcg2005` aux quatre points de creation/reinitialisation de
    tenant, qui l'appelaient de facon inconditionnelle : un tenant cree avec
    `--country=SN` recevait le plan comptable malgache. Le plan est ici resolu
    par le pays du tenant, conformement au cahier §12.2.
    """

    help = (
        "Charge le plan de comptes du referentiel actif du tenant (resolu par "
        "son pays). Jeux de donnees non valides par un expert-comptable."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            created = load_chart_of_accounts(tenant)
        if created == 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Aucun plan de comptes resolu pour le pays {tenant.country_code!r} "
                    f"de {tenant.code} — aucun compte cree."
                )
            )
            return
        self.stdout.write(self.style.SUCCESS(f"{created} compte(s) cree(s) pour {tenant.code}."))
