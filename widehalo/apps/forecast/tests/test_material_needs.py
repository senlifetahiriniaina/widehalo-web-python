"""Bloc F, F1 : `services.material_needs.compute_material_needs` —
explosion de `sales.SalesForecast` à travers la nomenclature `mrp`,
confrontée au stock disponible (`stocks`, déjà net des réservations) et
aux commandes fournisseur en cours (`purchase`)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.forecast.services.material_needs import compute_material_needs
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.purchase.models import PurOrder
from apps.purchase.tests.factories import PurOrderFactory, PurOrderLineFactory
from apps.sales.tests.factories import SalesForecastFactory
from apps.stocks.tests.factories import StkQuantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-F1", name="Forecast F1 Tenant")


def _variant(tenant: Tenant, *, code: str) -> tuple[ProductVariant, UnitOfMeasure]:
    uom = UnitOfMeasure.objects.create(
        tenant=tenant, code=f"PC-{code}", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
    )
    template = ProductTemplate.objects.create(tenant=tenant, name=f"Produit {code}", base_uom=uom)
    variant = ProductVariant.objects.create(tenant=tenant, template=template)
    return variant, uom


# Alias explicite pour la lisibilite des tests (meme helper, cote
# composant plutot que produit fini).
_component_variant = _variant


def test_compute_material_needs_aggregates_horizon_then_explodes_and_nets_against_supply(
    tenant: Tenant,
) -> None:
    with use_tenant(tenant.id):
        finished_variant, _finished_uom = _variant(tenant, code="FIN-AGG")
        SalesForecastFactory(
            tenant=tenant, variant_id=finished_variant.id, period="2026-01", qty_forecast=6
        )
        SalesForecastFactory(
            tenant=tenant, variant_id=finished_variant.id, period="2026-02", qty_forecast=4
        )

        component_variant, component_uom = _component_variant(tenant, code="AGG")
        bom = create_bom(
            tenant=tenant, code="BOM-F1-AGG", product_template_id=finished_variant.template_id
        )
        add_bom_line(
            bom,
            component_template_id=component_variant.template_id,
            component_variant_id=component_variant.id,
            qty=Decimal("2"),
        )
        activate_bom(bom)

        StkQuantFactory(tenant=tenant, variant_id=component_variant.id, qty=Decimal(5))
        open_order = PurOrderFactory(tenant=tenant, state=PurOrder.STATE_CONFIRMED)
        PurOrderLineFactory(
            tenant=tenant,
            order=open_order,
            variant_id=component_variant.id,
            qty=Decimal(3),
            qty_received=Decimal(0),
            uom=component_uom.code,
        )

        results = compute_material_needs(tenant, period_from="2026-01", period_to="2026-02")

        assert len(results) == 1
        need = results[0]
        assert need["component_variant_id"] == str(component_variant.id)
        assert need["gross_need"] == Decimal("20")  # (6 + 4) * 2
        assert need["available_stock"] == Decimal(5)
        assert need["on_order"] == Decimal(3)
        assert need["net_need"] == Decimal("12")  # 20 - 5 - 3


def test_compute_material_needs_floors_net_need_at_zero(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        finished_variant, _finished_uom = _variant(tenant, code="FIN-FLOOR")
        SalesForecastFactory(
            tenant=tenant, variant_id=finished_variant.id, period="2026-01", qty_forecast=2
        )

        component_variant, _uom = _component_variant(tenant, code="FLOOR")
        bom = create_bom(
            tenant=tenant, code="BOM-F1-FLOOR", product_template_id=finished_variant.template_id
        )
        add_bom_line(
            bom,
            component_template_id=component_variant.template_id,
            component_variant_id=component_variant.id,
            qty=Decimal("1"),
        )
        activate_bom(bom)

        StkQuantFactory(tenant=tenant, variant_id=component_variant.id, qty=Decimal(50))

        results = compute_material_needs(tenant, period_from="2026-01", period_to="2026-01")

        assert results[0]["net_need"] == Decimal(0)


def test_compute_material_needs_skips_products_without_active_bom(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        finished_variant, _finished_uom = _variant(tenant, code="FIN-NOBOM")
        SalesForecastFactory(
            tenant=tenant, variant_id=finished_variant.id, period="2026-01", qty_forecast=8
        )

        results = compute_material_needs(tenant, period_from="2026-01", period_to="2026-01")

        assert results == []


def test_compute_material_needs_ignores_forecasts_outside_the_horizon(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        finished_variant, _finished_uom = _variant(tenant, code="FIN-HORIZON")
        SalesForecastFactory(
            tenant=tenant, variant_id=finished_variant.id, period="2025-12", qty_forecast=100
        )

        component_variant, _uom = _component_variant(tenant, code="HORIZON")
        bom = create_bom(
            tenant=tenant, code="BOM-F1-HORIZON", product_template_id=finished_variant.template_id
        )
        add_bom_line(
            bom,
            component_template_id=component_variant.template_id,
            component_variant_id=component_variant.id,
            qty=Decimal("1"),
        )
        activate_bom(bom)

        results = compute_material_needs(tenant, period_from="2026-01", period_to="2026-01")

        assert results == []
