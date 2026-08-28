"""Tracabilite ascendante/descendante d'un lot (§5.8, ST8 du
sous-sequencement `stocks` — cf. plan) : tests unitaires de
`services.traceability.lot_traceability`, en complement du scenario
d'acceptance §5.8.7 n°5 (`tests/test_acceptance.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkLot, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.traceability import lot_traceability
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def trace_setup():
    tenant = Tenant.objects.create(code="STK-TRAC-T", name="Stocks Traceability Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot")
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
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        return tenant, warehouse, supplier, internal, client


def test_lot_traceability_empty_lot_no_moves(trace_setup) -> None:
    tenant, *_ = trace_setup
    with use_tenant(tenant.id):
        lot = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="LOT-EMPTY")
        result = lot_traceability(lot)
        assert result["upstream"] == []
        assert result["downstream"] == []
        assert result["current_locations"] == []
        assert result["lot"]["name"] == "LOT-EMPTY"


def test_lot_traceability_upstream_only(trace_setup) -> None:
    tenant, warehouse, supplier, internal, client = trace_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-UP")
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("100"),
            uom="m",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 10),
            move_type=StkMove.TYPE_RECEPTION,
            source_document="PCMD-2026-001",
            unit_cost_mga=Decimal("500"),
            lot=lot,
        )
        validate_move(move)

        result = lot_traceability(lot)
        assert len(result["upstream"]) == 1
        assert result["upstream"][0]["source_document"] == "PCMD-2026-001"
        assert result["downstream"] == []
        assert len(result["current_locations"]) == 1
        assert result["current_locations"][0]["qty"] == Decimal("100")


def test_lot_traceability_downstream_only_no_current_stock(trace_setup) -> None:
    """Un lot deja entierement livre n'a plus de stock courant a un
    emplacement interne, mais l'historique aval reste trace."""
    tenant, warehouse, supplier, internal, client = trace_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-DOWN")
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("50"),
            uom="m",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 5),
            move_type=StkMove.TYPE_RECEPTION,
            source_document="PCMD-2026-002",
            unit_cost_mga=Decimal("500"),
            lot=lot,
        )
        validate_move(reception)
        delivery = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("50"),
            uom="m",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 20),
            move_type=StkMove.TYPE_LIVRAISON,
            source_document="SCMD-2026-042",
            lot=lot,
        )
        validate_move(delivery)

        result = lot_traceability(lot)
        assert len(result["upstream"]) == 1
        assert len(result["downstream"]) == 1
        assert result["downstream"][0]["source_document"] == "SCMD-2026-042"
        assert result["current_locations"] == []


def test_lot_traceability_multiple_current_locations(trace_setup) -> None:
    tenant, warehouse, supplier, internal, client = trace_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-MULTI")
        other_internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A2",
            name="Rayon A2",
            type=StkLocation.TYPE_INTERNE,
        )
        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("80"),
            uom="m",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 3),
            move_type=StkMove.TYPE_RECEPTION,
            source_document="PCMD-2026-003",
            unit_cost_mga=Decimal("500"),
            lot=lot,
        )
        validate_move(reception)
        transfer = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("30"),
            uom="m",
            location_from=internal,
            location_to=other_internal,
            date=dt.date(2026, 1, 4),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
            lot=lot,
        )
        validate_move(transfer)

        result = lot_traceability(lot)
        locations = {row["location_code"]: row["qty"] for row in result["current_locations"]}
        assert locations == {"A1": Decimal("50"), "A2": Decimal("30")}
