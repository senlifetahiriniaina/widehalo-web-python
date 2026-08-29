"""REF2 (enrichissement referentiel LIFE MDG, cf. plan) : commande de
chargement du referentiel de normes EPI (`CatalogStandard`, CAT-NORM1) —
~25 normes citees par le document source LIFE MDG (hi-vis, anti-feu,
soudage, antistatique, arc electrique, pluie/froid, protection chimique,
agents infectieux, gants, antichute, chaussures, casques...). Meme patron
idempotent que `load_sector_certifications`/`load_material_references`
(get_or_create par code, jamais de doublon si la commande est rejouee).

Contenu du fixture (`fixtures/epi_standards.json`) indicatif, NON valide
par un organisme de certification independant — meme reserve documentee
que le reste du referentiel deja livre dans ce projet. Aucune donnee
reelle/confidentielle : uniquement des references publiques de
nomenclature de normes (le texte integral des normes reste payant et
n'est PAS reproduit ici)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import CatalogStandard
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

_FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "epi_standards.json"


class Command(BaseCommand):
    help = (
        "Charge le referentiel de normes EPI (CAT-NORM1, ~25 normes, jeu de "
        "donnees indicatif NON valide par un organisme de certification "
        "independant) pour un tenant. Idempotent par code de norme."
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
                f"{created} norme(s) EPI creee(s) pour {tenant.code} "
                f"({len(rows)} norme(s) dans le referentiel)."
            )
        )
