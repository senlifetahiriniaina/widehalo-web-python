"""REF2 (enrichissement referentiel LIFE MDG, cf. plan) : commande de
chargement des options de personnalisation (`CatalogCustomizationOption`,
broderie/serigraphie/sublimation/transfert thermocollant/floquage/gravure/
badge) avec leurs compatibilites matiere (M2M vers
`CatalogMaterialReference`, resolues par `code`). Meme patron idempotent
que `load_material_references`/`load_epi_standards` (get_or_create par
code) ; les compatibilites matiere sont reappliquees a chaque execution via
`.set()` (idempotent par construction).

**Dependance d'ordre** : necessite que `load_material_references` ait deja
ete execute pour ce tenant — un code de matiere absent du referentiel est
silencieusement ignore (`filter(code__in=...)`, pas d'erreur bloquante),
disclosed ici plutot que masque.

Contenu du fixture (`fixtures/customization_options.json`) indicatif, NON
valide par un professionnel de la personnalisation textile independant —
meme reserve documentee que le reste du referentiel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import CatalogCustomizationOption, CatalogMaterialReference
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "customization_options.json"
)


class Command(BaseCommand):
    help = (
        "Charge le referentiel d'options de personnalisation avec leurs "
        "compatibilites matiere (jeu de donnees indicatif, NON valide par "
        "un professionnel independant) pour un tenant. Idempotent par code."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        rows = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        created = 0
        with activate_tenant(tenant.id):
            for row in rows:
                option, was_created = CatalogCustomizationOption.objects.get_or_create(
                    tenant=tenant,
                    code=row["code"],
                    defaults={
                        "name": row["name"],
                        "technique": row["technique"],
                        "notes": row.get("notes", ""),
                    },
                )
                if was_created:
                    created += 1
                material_codes = row.get("compatible_material_codes", [])
                materials = CatalogMaterialReference.objects.filter(
                    tenant=tenant, code__in=material_codes
                )
                option.compatible_materials.set(materials)
        self.stdout.write(
            self.style.SUCCESS(
                f"{created} option(s) de personnalisation creee(s) pour {tenant.code} "
                f"({len(rows)} option(s) dans le referentiel)."
            )
        )
