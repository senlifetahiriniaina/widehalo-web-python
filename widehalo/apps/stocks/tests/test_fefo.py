"""STK-FEFO1 (premier perime premier sorti, ST6 du sous-sequencement
`stocks` — cf. plan) : `select_lot_fefo` — aide de SELECTION de lot,
distincte du moteur FIFO de valorisation (`services.moves`), qui reste
inchange (cf. docstring `services.quants.select_lot_fefo`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkQualityState
from apps.stocks.services.quality import set_quality_state
from apps.stocks.services.quants import select_lot_fefo
from apps.stocks.services.warehouses import create_location, create_warehouse
from apps.stocks.tests.factories import StkLotFactory, StkQuantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def fefo_setup():
    tenant = Tenant.objects.create(code="STK-FEFO-T", name="Stocks FEFO Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        return tenant, location


def test_select_lot_fefo_picks_earliest_expiring_lot_first(fefo_setup) -> None:
    tenant, location = fefo_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot_far = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2027, 6, 1)
        )
        lot_near = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2026, 9, 1)
        )
        lot_mid = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2027, 1, 1)
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_far, qty=Decimal("50")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_near, qty=Decimal("50")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_mid, qty=Decimal("50")
        )

        allocations = select_lot_fefo(variant_id, location=location, qty_needed=Decimal("30"))

        assert allocations == [{"lot_id": lot_near.id, "qty": Decimal("30")}]


def test_select_lot_fefo_splits_across_lots_when_earliest_insufficient(fefo_setup) -> None:
    tenant, location = fefo_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot_near = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2026, 9, 1)
        )
        lot_mid = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2027, 1, 1)
        )
        lot_far = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2027, 6, 1)
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_near, qty=Decimal("10")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_mid, qty=Decimal("5")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_far, qty=Decimal("50")
        )

        allocations = select_lot_fefo(variant_id, location=location, qty_needed=Decimal("22"))

        assert allocations == [
            {"lot_id": lot_near.id, "qty": Decimal("10")},
            {"lot_id": lot_mid.id, "qty": Decimal("5")},
            {"lot_id": lot_far.id, "qty": Decimal("7")},
        ]


def test_select_lot_fefo_excludes_lots_without_expiry_and_reserved_qty(fefo_setup) -> None:
    tenant, location = fefo_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot_no_expiry = StkLotFactory(tenant=tenant, variant_id=variant_id)
        lot_reserved = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2026, 9, 1)
        )
        lot_available = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2027, 1, 1)
        )
        StkQuantFactory(
            tenant=tenant,
            variant_id=variant_id,
            location=location,
            lot=lot_no_expiry,
            qty=Decimal("100"),
        )
        StkQuantFactory(
            tenant=tenant,
            variant_id=variant_id,
            location=location,
            lot=lot_reserved,
            qty=Decimal("10"),
            qty_reserved=Decimal("10"),
        )
        StkQuantFactory(
            tenant=tenant,
            variant_id=variant_id,
            location=location,
            lot=lot_available,
            qty=Decimal("20"),
        )

        allocations = select_lot_fefo(variant_id, location=location, qty_needed=Decimal("15"))

        assert allocations == [{"lot_id": lot_available.id, "qty": Decimal("15")}]


def test_select_lot_fefo_returns_partial_allocation_when_insufficient_stock(fefo_setup) -> None:
    tenant, location = fefo_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot = StkLotFactory(tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2026, 9, 1))
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot, qty=Decimal("5")
        )

        allocations = select_lot_fefo(variant_id, location=location, qty_needed=Decimal("20"))

        assert allocations == [{"lot_id": lot.id, "qty": Decimal("5")}]


def test_select_lot_fefo_excludes_a_held_lot_even_when_earliest_expiring(fefo_setup) -> None:
    """STK-4 (Phase 3, sprint A2) : « un lot bloqué n'apparaît ni dans le
    disponible, ni dans la proposition FEFO » — même s'il est le lot le
    plus urgent en date de péremption, un lot bloqué (`en_quarantaine`)
    est ignoré ; le lot suivant, non bloqué, est proposé à sa place."""
    tenant, location = fefo_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot_held = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2026, 9, 1)
        )
        lot_next = StkLotFactory(
            tenant=tenant, variant_id=variant_id, date_expiry=dt.date(2027, 1, 1)
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_held, qty=Decimal("50")
        )
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=location, lot=lot_next, qty=Decimal("50")
        )
        set_quality_state(tenant=tenant, lot=lot_held, state=StkQualityState.STATE_EN_QUARANTAINE)

        allocations = select_lot_fefo(variant_id, location=location, qty_needed=Decimal("30"))

        assert allocations == [{"lot_id": lot_next.id, "qty": Decimal("30")}]
