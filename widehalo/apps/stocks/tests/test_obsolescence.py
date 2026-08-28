"""STK-OBS1 (stock dormant/obsolescence, ST6 du sous-sequencement `stocks`
— cf. plan) : `dormant_stock_report` — indicateur de rotation par (produit,
emplacement), flag `is_dormant` au-dela d'un seuil d'immobilisation
parametrable (defaut 180 jours)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.obsolescence import dormant_stock_report
from apps.stocks.services.warehouses import create_location, create_warehouse
from apps.stocks.tests.factories import StkQuantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def obsolescence_setup():
    tenant = Tenant.objects.create(code="STK-OBS-T", name="Stocks Obsolescence Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        return tenant, supplier, internal


def test_dormant_stock_report_flags_quant_beyond_threshold(obsolescence_setup) -> None:
    tenant, supplier, internal = obsolescence_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("10"),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2025, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("100"),
        )
        validate_move(move)

        as_of = dt.date(2026, 8, 1)
        report = dormant_stock_report(tenant, as_of=as_of, immobilization_threshold_days=180)
        row = next(r for r in report if r["variant_id"] == variant_id)

        assert row["qty"] == Decimal("10")
        assert row["days_since_last_movement"] == (as_of - dt.date(2025, 1, 1)).days
        assert row["is_dormant"] is True


def test_dormant_stock_report_not_dormant_below_threshold(obsolescence_setup) -> None:
    tenant, supplier, internal = obsolescence_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("10"),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 7, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("100"),
        )
        validate_move(move)

        as_of = dt.date(2026, 8, 1)
        report = dormant_stock_report(tenant, as_of=as_of, immobilization_threshold_days=180)
        row = next(r for r in report if r["variant_id"] == variant_id)

        assert row["is_dormant"] is False


def test_dormant_stock_report_excludes_zero_qty_and_virtual_locations(obsolescence_setup) -> None:
    tenant, supplier, internal = obsolescence_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=internal, qty=Decimal("0"))
        StkQuantFactory(
            tenant=tenant, variant_id=uuid.uuid4(), location=supplier, qty=Decimal("-5")
        )

        report = dormant_stock_report(tenant, as_of=dt.date(2026, 8, 1))
        assert report == []


def test_dormant_stock_report_marks_dormant_without_any_done_move(obsolescence_setup) -> None:
    """Un quant sans aucun `StkMove` `done` correspondant (donnee
    incoherente, ex. import direct) est traite comme dormant par defaut —
    `days_since_last_movement` reste `None`, jamais une valeur inventee."""
    tenant, _supplier, internal = obsolescence_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=internal, qty=Decimal("4"))

        report = dormant_stock_report(tenant, as_of=dt.date(2026, 8, 1))
        row = next(r for r in report if r["variant_id"] == variant_id)
        assert row["days_since_last_movement"] is None
        assert row["is_dormant"] is True
