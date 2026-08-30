from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.helpdesk.services.catalog_loader import load_ticket_type_catalog


class Command(BaseCommand):
    help = (
        "Charge le catalogue de types de demandes/incidents (jeu de donnees de "
        "depart editable, non valide par un expert metier) pour un tenant."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            created = load_ticket_type_catalog(tenant)
        self.stdout.write(self.style.SUCCESS(f"{created} entree(s) creee(s) pour {tenant.code}."))
