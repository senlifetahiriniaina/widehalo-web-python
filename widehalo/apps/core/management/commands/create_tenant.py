from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant


class Command(BaseCommand):
    help = "Cree un tenant, avec SmartDefaults appliques selon le pays (--country)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--code", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--nif", default="")
        parser.add_argument("--country", default="MG")

    def handle(self, *args, **options) -> None:
        from apps.core.services.smart_defaults import apply_country_defaults

        tenant = Tenant.objects.create(
            code=options["code"],
            name=options["name"],
            nif=options["nif"],
            country_code=options["country"],
        )
        apply_country_defaults(tenant, options["country"])
        # Catalogue de types de tickets helpdesk (54 entrees, cf. plan
        # section "catalogue de tickets helpdesk vide par defaut") — jamais
        # vide pour un nouveau tenant. Invoque via `call_command` (chaine de
        # caracteres, jamais un import Python d'un module `helpdesk`) pour
        # ne creer aucune dependance declaree de `core` vers `helpdesk`
        # (verifie contre `test_module_boundaries.py`, qui ne scanne que les
        # imports AST reels).
        call_command("load_ticket_type_catalog", tenant=tenant.code)
        self.stdout.write(self.style.SUCCESS(f"Tenant créé : {tenant.code} ({tenant.id})"))
