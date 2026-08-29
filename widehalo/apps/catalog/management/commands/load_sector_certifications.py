"""SEC2 (extension sectorielle Madagascar, cf. plan) : commande de
chargement du referentiel de normes CAT-NORM1 (`CatalogStandard`) pour les
secteurs cuir, agroalimentaire et artisanat — meme patron idempotent que
`accounting.load_pcg2005`/`strategy.load_textile_benchmarks` (get_or_create
par code de norme, jamais de doublon si la commande est rejouee).

Contenu du fixture (`fixtures/sector_certifications.json`) indicatif, NON
valide par un expert sectoriel independant (cuir, agroalimentaire,
artisanat) — meme reserve documentee que le PCG 2005 ou les benchmarks
textile deja livres dans ce projet. Aucune donnee reelle/confidentielle.

Le champ `sector_code` du fixture est purement documentaire (traçabilite de
la source) : il n'est PAS persiste sur `CatalogStandard`, qui reste un
referentiel de normes generique non rattache a un secteur (CAT-NORM1,
meme mecanisme deja construit pour le textile)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import CatalogStandard
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "sector_certifications.json"
)


class Command(BaseCommand):
    help = (
        "Charge le referentiel de normes/certifications (CAT-NORM1) pour les "
        "secteurs cuir, agroalimentaire et artisanat (jeu de donnees "
        "indicatif, NON valide par un expert sectoriel independant) pour un "
        "tenant. Idempotent par code de norme."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        rows = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        created = 0
        with activate_tenant(tenant.id):
            for row in rows:
                _, was_created = CatalogStandard.objects.get_or_create(
                    tenant=tenant,
                    code=row["code"],
                    defaults={
                        "name": row["name"],
                        "description": row.get("description", ""),
                    },
                )
                if was_created:
                    created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"{created} norme(s) sectorielle(s) creee(s) pour {tenant.code} "
                f"({len(rows)} norme(s) dans le referentiel)."
            )
        )
