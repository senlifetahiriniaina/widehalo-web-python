"""Charge le catalogue par defaut des produits (30 EPI/vetements techniques
fabricables a Madagascar, perimetre coupe-couture-ennoblissement uniquement
-- cf. le document source qui delimite lui-meme ce Volet 2 comme le seul
realistement fabricable avec le savoir-faire couvert par cet ERP, a
l'exclusion du Top 100 mondial elargi qui suppose injection plastique/
moulage caoutchouc/trempage latex).

Contrairement a `load_sample_products.py`, ceci EST un catalogue reel de
tenant, pre-charge a l'initialisation de toute entreprise (cf.
`create_tenant`, `setup_company_view`, `reset_tenant_data`) -- jamais
present dans les scripts de demonstration (`seed_core`/`seed_crm`/
`seed_catalog`). Libre aux administrateurs de le modifier ou de le
supprimer ensuite.

Meme patron idempotent que le reste du referentiel deja livre dans ce
projet : `get_or_create` par `reference` (le `code` du fixture) pour les
templates, et par variante unique (premiere/seule variante du template)
pour `TextileSpec`/`CatalogCertification`. Un code matiere/norme absent du
referentiel deja charge (`load_material_references`/`load_epi_standards`)
est silencieusement ignore, jamais fabrique -- cf. le produit
"Manchon anti-coupure tricote" (fibre HPPE absente du referentiel), dont
`material_code` est volontairement omis dans le fixture plutot que devine.

**Reserve methodologique explicite sur `base_price_mga`** : ce montant est
un POINT DE DEPART INDICATIF, derive du prix de VENTE export UE cite par le
document source (jamais un cout de revient malgache), converti via un taux
approximatif documente (EUR->MGA ~5190, derive du seul chiffre de change
deja cite par le document source lui-meme -- le SMIG malgache 2024,
262680 Ar = 50,60 EUR ; GBP->EUR ~1,15 pour les quelques entrees GBP,
valeur usuelle approximative). Ce n'est ni un taux de change officiel
garanti a jour, ni un cout de revient calcule -- a ajuster librement par
l'administrateur. Contenu indicatif, non valide par un expert
textile/EPI independant, meme reserve que le reste du referentiel deja
livre dans ce projet (materiaux, normes, options de personnalisation)."""

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
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "default_product_catalog.json"
)


class Command(BaseCommand):
    help = (
        "Charge le catalogue par defaut des produits (30 EPI/vetements techniques "
        "fabricables a Madagascar) -- un vrai catalogue de tenant, librement "
        "modifiable/supprimable par les administrateurs. Idempotent par reference "
        "de produit."
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
                f"{created} produit(s) du catalogue par defaut cree(s) pour {tenant.code} "
                f"({len(rows)} produit(s) dans le referentiel)."
            )
        )
