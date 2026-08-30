"""INT4 (chantier interactivite native inter-modules — « faire le max avec
AutoFlow ») : commande de management qui construit, pour UN tenant donne,
le jeu complet de flux `AutoFlow` REELS/ACTIFS reliant les `event_type`
ajoutes par INT1 (et les evenements preexistants pertinents) aux actions
deja enregistrees dans `core.services.automation_registry` — meme patron
que `apps.accounting.management.commands.load_pcg2005` (commande
`seed_<module>`, `--tenant`/tenant lookup, `activate_tenant`).

Toute la logique de construction/idempotence vit dans
`apps.automation.services.seed_flows.seed_default_flows` — cette commande
n'est qu'un point d'entree CLI mince autour de ce service."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.automation.services.seed_flows import seed_default_flows
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    help = (
        "Cree (idempotent, identifie par le nom du flux) et active un jeu complet de "
        "flux AutoFlow reliant les evenements metier publies aux actions du registre "
        "d'automatisation, pour un tenant donne."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant-id", required=True, help="Identifiant (UUID) du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(id=options["tenant_id"])
        with activate_tenant(tenant.id):
            results = seed_default_flows(tenant)

        created_count = sum(1 for _flow, created in results if created)
        skipped_count = len(results) - created_count
        for flow, created in results:
            status = "cree+active" if created else "deja present (inchange)"
            self.stdout.write(f"- {flow.name} [{flow.trigger_event_type}] : {status}")
        self.stdout.write(
            self.style.SUCCESS(
                f"{created_count} flux cree(s) et active(s), {skipped_count} deja present(s) "
                f"pour {tenant.code}."
            )
        )
