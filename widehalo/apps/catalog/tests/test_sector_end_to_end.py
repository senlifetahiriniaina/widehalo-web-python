"""SEC3 (extension sectorielle Madagascar, cf. plan) : scenarios de bout en
bout demontrant que les 3 nouveaux secteurs (cuir, agroalimentaire,
artisanat) reutilisent SANS AUCUNE MODIFICATION les mecanismes generiques
deja construits pour le textile — `mrp.MrpBomLine.qty_by_size`,
`patronage` (grilles de tailles/gradation), `stocks.StkLot`
(peremption/tracabilite). Rien ici n'exerce du code nouveau dans ces 3
modules : ce fichier vit dans `catalog` et importe directement leurs
modeles (tests exemptes du garde-fou de couplage inter-modules, cf.
`tests/architecture/_ast_utils.iter_app_python_files(exclude_tests=True)`)
uniquement pour PROUVER la reutilisation, jamais pour y ajouter une
dependance de production (`catalog/module.py` ne declare toujours que
`core`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.catalog.models import CatalogSectorSpec, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.catalog.services.sector_specs import create_sector_spec
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBom, MrpBomLine
from apps.patronage.models import (
    PatGradingRule,
    PatMeasurementPoint,
    PatSizeChart,
    PatSizeChartValue,
)
from apps.patronage.services.grading import apply_grading
from apps.stocks.models import StkLot

pytestmark = pytest.mark.django_db


def _make_variant(
    tenant: Tenant, uom: UnitOfMeasure, *, name: str, reference: str
) -> ProductVariant:
    template = ProductTemplate.objects.create(
        tenant=tenant, name=name, base_uom=uom, reference=f"TPL-{reference}"
    )
    return ProductVariant.objects.create(tenant=tenant, template=template, reference=reference)


def test_leather_product_with_sector_spec_can_be_used_in_a_generic_bom() -> None:
    """Un sac en cuir (CatalogSectorSpec secteur `cuir`) entre comme
    composant d'une nomenclature `mrp` avec un `qty_by_size` generique
    (ici par TAILLE de sac, pas par taille vestimentaire) — sans aucune
    adaptation du modele `MrpBomLine`."""
    tenant = Tenant.objects.create(code="SEC-E2E-CUIR", name="Sector E2E Cuir Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        finished_good = _make_variant(tenant, uom, name="Sac a main", reference="VAR-SAC-0001")
        leather = _make_variant(tenant, uom, name="Cuir chevre vegetal", reference="VAR-CUIR-0001")

        spec = create_sector_spec(
            leather,
            sector_code=CatalogSectorSpec.SECTOR_CUIR,
            attributes={"type_peau": "chevre", "tannage": "vegetal", "epaisseur_mm": 1.4},
        )
        assert spec.sector_code == CatalogSectorSpec.SECTOR_CUIR

        bom = MrpBom.objects.create(
            tenant=tenant,
            code="BOM-SAC-0001",
            product_template_id=finished_good.template_id,
            variant_id=finished_good.id,
        )
        line = MrpBomLine.objects.create(
            tenant=tenant,
            bom=bom,
            component_template_id=leather.template_id,
            component_variant_id=leather.id,
            qty=Decimal("1"),
            # RG-MRP-2 : cle arbitraire ("S"/"M"/"L" de SAC, pas de
            # vetement) -> qty_by_size ne suppose rien de textile.
            qty_by_size={"S": "0.8", "M": "1.2", "L": "1.6"},
        )
        assert line.qty_by_size["M"] == "1.2"


def test_artisanat_product_can_be_graded_via_patronage_size_chart() -> None:
    """Un panier en raphia (artisanat) gradue par `patronage`
    (`PatSizeChart`/`PatGradingRule`/`apply_grading`) exactement comme un
    vetement — aucune notion de vetement dans ce mecanisme."""
    tenant = Tenant.objects.create(code="SEC-E2E-ART", name="Sector E2E Artisanat Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        basket = _make_variant(tenant, uom, name="Panier raphia", reference="VAR-PANIER-0001")
        spec = create_sector_spec(
            basket,
            sector_code=CatalogSectorSpec.SECTOR_ARTISANAT,
            attributes={
                "matiere_premiere": "raphia",
                "technique": "tressage",
                "origine_artisan": "Antsirabe",
            },
        )
        assert spec.sector_code == CatalogSectorSpec.SECTOR_ARTISANAT

        chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="PANIER",
            name="Panier raphia",
            # GARMENT_CHOICES est le vocabulaire herite du textile (aucune
            # entree "accessoire non-vestimentaire" dediee) — reutilise en
            # l'etat, la valeur GARMENT_ACCESSORY reste la plus proche
            # semantiquement pour un objet d'artisanat gradue par taille ;
            # simplification documentee, hors perimetre de ce chantier
            # (ne modifie aucun modele `patronage`).
            garment_type=PatSizeChart.GARMENT_ACCESSORY,
            sizes=["S", "M", "L"],
            base_size="S",
        )
        diameter = PatMeasurementPoint.objects.create(
            tenant=tenant, code="diametre", name="Diametre du panier"
        )
        PatSizeChartValue.objects.create(
            tenant=tenant, size_chart=chart, measurement_point=diameter, size="S", value=Decimal(20)
        )
        PatGradingRule.objects.create(
            tenant=tenant,
            size_chart=chart,
            measurement_point=diameter,
            mode=PatGradingRule.MODE_FIXED,
            value=Decimal(5),
            from_size="S",
            to_size="L",
        )
        graded = apply_grading(chart)
        assert graded["diametre"]["S"] == Decimal(20)
        assert graded["diametre"]["M"] == Decimal(25)
        assert graded["diametre"]["L"] == Decimal(30)


def test_agrifood_product_is_tracked_by_lot_and_expiry_via_stocks() -> None:
    """Un produit agroalimentaire (CatalogSectorSpec secteur
    `agroalimentaire`, fiche PRODUIT statique avec allergenes/conditions de
    conservation) est trace par LOT physique reel via `stocks.StkLot`
    (peremption FEFO deja construit en ST6) — les deux mecanismes
    coexistent sans duplication (fiche catalogue vs. lot reel, cf.
    docstring `services/sector_specs.py`)."""
    tenant = Tenant.objects.create(code="SEC-E2E-AGRO", name="Sector E2E Agro Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="KG", name="Kilogramme", category=UnitOfMeasure.CATEGORY_WEIGHT
        )
        honey = _make_variant(tenant, uom, name="Miel de litchi", reference="VAR-MIEL-0001")
        spec = create_sector_spec(
            honey,
            sector_code=CatalogSectorSpec.SECTOR_AGROALIMENTAIRE,
            attributes={
                "composition": {"miel": 100},
                "allergenes": [],
                "conditions_conservation": "Sec, a l'abri de la lumiere, 18-25°C",
            },
        )
        assert spec.sector_code == CatalogSectorSpec.SECTOR_AGROALIMENTAIRE

        lot = StkLot.objects.create(
            tenant=tenant,
            variant_id=honey.id,
            name="LOT-MIEL-2026-001",
            date_production=dt.date(2026, 1, 15),
            date_expiry=dt.date(2027, 1, 15),
        )
        assert lot.variant_id == honey.id
        assert lot.date_expiry == dt.date(2027, 1, 15)
