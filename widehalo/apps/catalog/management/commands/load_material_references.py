"""REF1 (enrichissement referentiel LIFE MDG, cf. plan) : commande de
chargement du referentiel de matieres fibres/tissus (`CatalogMaterialReference`)
— meme patron idempotent que `load_sector_certifications`/
`accounting.load_pcg2005`/`strategy.load_textile_benchmarks` (get_or_create
par code, jamais de doublon si la commande est rejouee).

Contenu du fixture (`fixtures/materials_reference_mg.json`) indicatif, NON
valide par un expert textile independant — meme reserve documentee que le
PCG 2005, les benchmarks textile et les normes sectorielles deja livres
dans ce projet. Aucune donnee reelle/confidentielle. Les fourchettes de
grammage sont celles du document source LIFE MDG, explicitement qualifiees
par ce dernier de non-absolues (varient par fabricant/construction/lavage)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import CatalogMaterialReference
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "materials_reference_mg.json"
)


class Command(BaseCommand):
    help = (
        "Charge le referentiel de matieres fibres/tissus (jeu de donnees "
        "indicatif, NON valide par un expert textile independant) pour un "
        "tenant. Idempotent par code de matiere."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        rows = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        created = 0
        with activate_tenant(tenant.id):
            for row in rows:
                _, was_created = CatalogMaterialReference.objects.get_or_create(
                    tenant=tenant,
                    code=row["code"],
                    defaults={
                        "name": row["name"],
                        "nature": row["nature"],
                        "typical_gsm_min": row.get("typical_gsm_min"),
                        "typical_gsm_max": row.get("typical_gsm_max"),
                        "usage_notes": row.get("usage_notes", ""),
                        "supplier_reference": row.get("supplier_reference", ""),
                    },
                )
                if was_created:
                    created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"{created} matiere(s) de reference creee(s) pour {tenant.code} "
                f"({len(rows)} matiere(s) dans le referentiel)."
            )
        )
