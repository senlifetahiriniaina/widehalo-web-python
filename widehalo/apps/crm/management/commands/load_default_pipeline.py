"""Commande de chargement idempotente du pipeline commercial par defaut
(HubSpot, 7 etapes, cf. `apps.crm.services.pipelines`) — meme convention que
`load_pcg2005`/`load_default_journals`/`load_ticket_type_catalog`."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.crm.services.pipelines import ensure_default_pipeline


class Command(BaseCommand):
    help = "Charge le pipeline commercial par defaut (7 etapes) pour un tenant. Idempotent."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            pipeline = ensure_default_pipeline(tenant)
        self.stdout.write(
            self.style.SUCCESS(f"Pipeline par defaut '{pipeline.name}' pret pour {tenant.code}.")
        )
