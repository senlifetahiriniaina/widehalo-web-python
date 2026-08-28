"""STK-REDIS1 (redistribution inter-sites, ST6 du sous-sequencement
`stocks` — cf. plan) : `suggest_redistribution` — suggestion pure, ne cree
jamais de mouvement (cf. docstring `services/redistribution.py`)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation
from apps.stocks.services.redistribution import suggest_redistribution
from apps.stocks.services.warehouses import create_location, create_warehouse
from apps.stocks.tests.factories import StkQuantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def redistribution_setup():
    tenant = Tenant.objects.create(code="STK-REDIS-T", name="Stocks Redistribution Tenant")
    with use_tenant(tenant.id):
        warehouse_a = create_warehouse(tenant=tenant, code="WH-A", name="Site A")
        warehouse_b = create_warehouse(tenant=tenant, code="WH-B", name="Site B")
        location_a = create_location(
            tenant=tenant,
            warehouse=warehouse_a,
            code="A1",
            name="Rayon A",
            type=StkLocation.TYPE_INTERNE,
        )
        location_b = create_location(
            tenant=tenant,
            warehouse=warehouse_b,
            code="B1",
            name="Rayon B",
            type=StkLocation.TYPE_INTERNE,
        )
        return tenant, warehouse_a, warehouse_b, location_a, location_b


def test_suggest_redistribution_pairs_shortage_with_excess(redistribution_setup) -> None:
    """Site A en rupture (qty=0, seuil=0), site B a de l'excedent
    (qty=30, qty_reserved=10 => disponible=20). `shortage_qty` = 0-0 = 0,
    `available_excess_qty` = 20, `suggested_qty` = min(0, 20) = 0 — pour
    exercer un manque REEL, on utilise un seuil de rupture positif (5)."""
    tenant, warehouse_a, warehouse_b, location_a, location_b = redistribution_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location_a, qty=Decimal("2"))
        StkQuantFactory(
            tenant=tenant,
            variant_id=variant_id,
            location=location_b,
            qty=Decimal("30"),
            qty_reserved=Decimal("10"),
        )

        suggestions = suggest_redistribution(tenant, shortage_threshold=Decimal("5"))

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion["variant_id"] == variant_id
        assert suggestion["from_warehouse_id"] == warehouse_b.id
        assert suggestion["from_location_id"] == location_b.id
        assert suggestion["to_warehouse_id"] == warehouse_a.id
        assert suggestion["to_location_id"] == location_a.id
        # shortage_qty = 5 - 2 = 3 ; available_excess_qty = 30 - 10 = 20 ;
        # suggested_qty = min(3, 20) = 3.
        assert suggestion["shortage_qty"] == Decimal("3")
        assert suggestion["available_excess_qty"] == Decimal("20")
        assert suggestion["suggested_qty"] == Decimal("3")


def test_suggest_redistribution_no_suggestion_without_excess_elsewhere(
    redistribution_setup,
) -> None:
    tenant, _warehouse_a, _warehouse_b, location_a, location_b = redistribution_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location_a, qty=Decimal("1"))
        # Le site B a du stock mais integralement reserve : excedent nul.
        StkQuantFactory(
            tenant=tenant,
            variant_id=variant_id,
            location=location_b,
            qty=Decimal("10"),
            qty_reserved=Decimal("10"),
        )

        suggestions = suggest_redistribution(tenant, shortage_threshold=Decimal("5"))
        assert suggestions == []


def test_suggest_redistribution_no_suggestion_when_nothing_short(redistribution_setup) -> None:
    tenant, _warehouse_a, _warehouse_b, location_a, location_b = redistribution_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location_a, qty=Decimal("50")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location_b, qty=Decimal("50")
        )

        suggestions = suggest_redistribution(tenant, shortage_threshold=Decimal("5"))
        assert suggestions == []


def test_suggest_redistribution_picks_warehouse_with_most_excess(redistribution_setup) -> None:
    tenant, warehouse_a, warehouse_b, location_a, location_b = redistribution_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        warehouse_c = create_warehouse(tenant=tenant, code="WH-C", name="Site C")
        location_c = create_location(
            tenant=tenant,
            warehouse=warehouse_c,
            code="C1",
            name="Rayon C",
            type=StkLocation.TYPE_INTERNE,
        )
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location_a, qty=Decimal("0"))
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location_b, qty=Decimal("15")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location_c, qty=Decimal("40")
        )

        suggestions = suggest_redistribution(tenant, shortage_threshold=Decimal("5"))
        assert len(suggestions) == 1
        assert suggestions[0]["from_warehouse_id"] == warehouse_c.id
