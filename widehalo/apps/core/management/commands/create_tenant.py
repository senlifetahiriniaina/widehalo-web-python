from __future__ import annotations

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
        self.stdout.write(self.style.SUCCESS(f"Tenant créé : {tenant.code} ({tenant.id})"))
