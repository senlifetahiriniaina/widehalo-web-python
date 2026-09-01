"""REF3 (enrichissement referentiel LIFE MDG, cf. plan) : commande de
chargement de produits de DEMONSTRATION/REFERENCE — PAS un catalogue reel
de tenant. Charge trois familles de donnees issues du document source LIFE
MDG, toutes explicitement disclosed comme demonstratives (docstring +
champ `notes` de chaque `ProductTemplate`, cf. fixture) :

1. **Composants semi-finis (trims)** : zips YKK (Coil/Metal/Vislon),
   bouton, pression, velcro, bande retro-reflechissante, doublure — des
   `ProductTemplate`/`ProductVariant` ORDINAIRES dans la categorie
   "Composants", consommables par `mrp.MrpBomLine` exactement comme
   n'importe quel composant (AUCUNE nouvelle entite necessaire, confirme
   par l'audit prealable du chantier, cf. plan).
2. **Produits d'exemple par famille** (haut du corps, bas du corps, une
   piece, couvre-chefs, chaussures, sport...) avec matiere/grammage
   (`TextileSpec`, via `CatalogMaterialReference` quand pertinent) et
   normes applicables (`CatalogCertification` vers les normes EPI
   chargees par `load_epi_standards` — un code de norme absent est
   silencieusement ignore, meme discipline de dependance d'ordre que
   `load_customization_options`).
3. **Contextes culturels malgaches (lamba)** : lambamena (soie, linceul
   funeraire), lambahoany (coton imprime du quotidien), lamba akotofahana
   (soie, motifs geometriques nobles), Jabo-Landy (soie+coton), salaka
   (pagne traditionnel) — categorie dediee "Lambas (patrimoine culturel
   malgache)".

Meme patron idempotent que les autres commandes `load_*` de ce chantier :
`get_or_create` par `reference` (le `code` du fixture) pour les templates,
et par variante unique (premiere/seule variante du template) pour
`TextileSpec`/`CatalogCertification`. Contenu du fixture
(`fixtures/sample_products_by_family.json`) indicatif, NON valide par un
expert textile/EPI/culturel independant — meme reserve documentee que le
reste du referentiel deja livre dans ce projet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import (
    CatalogCertification,
    CatalogMaterialReference,
    CatalogStandard,
    Category,
    ProductTemplate,
    ProductVariant,
    TextileSpec,
    UnitOfMeasure,
)
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "sample_products_by_family.json"
)


class Command(BaseCommand):
    help = (
        "Charge des produits de DEMONSTRATION/REFERENCE (composants trims, "
        "exemples de produits par famille, lamba malgaches) — PAS un "
        "catalogue reel de tenant. Jeu de donnees indicatif, NON valide "
        "par un expert independant. Idempotent par reference de produit."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        rows = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        created = 0
        with activate_tenant(tenant.id):
            pcs, _ = UnitOfMeasure.objects.get_or_create(
                tenant=tenant,
                code="PCS",
                defaults={"name": "Piece", "category": UnitOfMeasure.CATEGORY_COUNT},
            )
            materials_by_code = {
                m.code: m for m in CatalogMaterialReference.objects.filter(tenant=tenant)
            }
            for row in rows:
                category, _ = Category.objects.get_or_create(tenant=tenant, name=row["category"])
                template, was_created = ProductTemplate.objects.get_or_create(
                    tenant=tenant,
                    reference=row["code"],
                    defaults={
                        "name": row["name"],
                        "category": category,
                        "base_uom": pcs,
                        "base_price_mga": row["base_price_mga"],
                        # Un composant/trim (categorie "Composants") n'est
                        # jamais vendu tel quel, seulement consomme par une
                        # nomenclature MRP — jamais vendable, contrairement
                        # aux produits finis (haut/bas du corps, lambas...).
                        "is_sellable": row["category"] != "Composants",
                    },
                )
                if was_created:
                    created += 1

                variant = template.variants.first()
                if variant is None:
                    variant = ProductVariant.objects.create(
                        tenant=tenant, template=template, reference=f"{row['code']}-V1"
                    )

                material_code = row.get("material_code")
                if material_code:
                    material = materials_by_code.get(material_code)
                    TextileSpec.objects.get_or_create(
                        tenant=tenant,
                        variant=variant,
                        defaults={
                            "material": material.name if material else material_code,
                            "weight_gsm": row.get("weight_gsm"),
                        },
                    )

                standard_codes = row.get("standard_codes", [])
                if standard_codes:
                    standards = CatalogStandard.objects.filter(
                        tenant=tenant, code__in=standard_codes
                    )
                    for standard in standards:
                        CatalogCertification.objects.get_or_create(
                            tenant=tenant, variant=variant, standard=standard
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{created} produit(s) de demonstration cree(s) pour {tenant.code} "
                f"({len(rows)} produit(s) dans le referentiel). "
                "Rappel : donnees de demonstration/reference, PAS un catalogue reel."
            )
        )
