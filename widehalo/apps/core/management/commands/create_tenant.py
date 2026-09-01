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
        # Plan comptable PCG 2005 (generique + sectoriel, cf. UXR7) et 7
        # journaux comptables par defaut — jamais vides pour un nouveau
        # tenant, meme convention `call_command` que le catalogue helpdesk
        # ci-dessus. PCG charge AVANT les journaux : `load_default_journals`
        # resout `default_account` (BQ/CAI) par prefixe de code parmi les
        # comptes deja crees, donc l'ordre importe.
        call_command("load_pcg2005", tenant=tenant.code)
        call_command("load_default_journals", tenant=tenant.code)
        self.stdout.write(self.style.SUCCESS(f"Tenant créé : {tenant.code} ({tenant.id})"))
