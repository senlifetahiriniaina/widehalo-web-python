"""Commande de chargement idempotente des motifs de perte d'opportunite par
defaut (7 categories metier, cf. `apps.crm.services.lost_reasons`) — meme
convention que `load_default_pipeline`/`load_pcg2005`/`load_default_
journals`/`load_ticket_type_catalog`."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.crm.services.lost_reasons import ensure_default_lost_reasons


class Command(BaseCommand):
    help = "Charge les 7 motifs de perte d'opportunite par defaut pour un tenant. Idempotent."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            reasons = ensure_default_lost_reasons(tenant)
        self.stdout.write(
            self.style.SUCCESS(f"{len(reasons)} motif(s) de perte pret(s) pour {tenant.code}.")
        )
