"""STK-5 (cahier Phase 3 §5.8, sprint A1) : transfert entre entrepôts
distincts en deux phases (`services.moves.transfer_between_warehouses`
puis `receive_warehouse_transfer`), via un emplacement `TYPE_TRANSIT`
scopé à l'entrepôt de destination — « état "en transit" qui rend la
quantité indisponible sans la faire disparaître »."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import (
    create_move,
    receive_warehouse_transfer,
    transfer_between_warehouses,
    validate_move,
)
from apps.stocks.services.quants import get_quant
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def transfer_setup():
    tenant = Tenant.objects.create(code="STK-XFER-T", name="Stocks Transfer Tenant")
    with use_tenant(tenant.id):
        source_wh = create_warehouse(tenant=tenant, code="WH-SRC", name="Entrepot source")
        source_internal = create_location(
            tenant=tenant,
            warehouse=source_wh,
            code="SRC-A1",
            name="Rayon source",
            type=StkLocation.TYPE_INTERNE,
        )
        destination_wh = create_warehouse(tenant=tenant, code="WH-DST", name="Entrepot destination")
        destination_internal = create_location(
            tenant=tenant,
            warehouse=destination_wh,
            code="DST-A1",
            name="Rayon destination",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=source_wh,
            code="SRC-FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        return tenant, source_wh, source_internal, destination_wh, destination_internal, supplier


def _receive_into_source(tenant, supplier, source_internal, *, variant_id, qty):
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="pc",
        location_from=supplier,
        location_to=source_internal,
        date=dt.date(2026, 1, 1),
        move_type=StkMove.TYPE_RECEPTION,
        unit_cost_mga=Decimal("1000"),
    )
    return validate_move(move)


def test_transfer_between_warehouses_moves_stock_to_transit_location(transfer_setup) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(20)
        )

        departure = transfer_between_warehouses(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            source_warehouse=source_wh,
            destination_warehouse=destination_wh,
            date=dt.date(2026, 1, 2),
        )

        assert departure.state == StkMove.STATE_DONE
        assert departure.location_to.type == StkLocation.TYPE_TRANSIT
        assert departure.location_to.warehouse_id == destination_wh.id

        source_quant = get_quant(variant_id, source_internal)
        assert source_quant.qty == Decimal("8.0000")
        transit_quant = get_quant(variant_id, departure.location_to)
        assert transit_quant.qty == Decimal("12.0000")


def test_transfer_between_warehouses_refuses_same_warehouse(transfer_setup) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(5)
        )
        with pytest.raises(Exception, match="entrepôts distincts"):
            transfer_between_warehouses(
                tenant=tenant,
                variant_id=variant_id,
                qty=Decimal(5),
                uom="pc",
                source_warehouse=source_wh,
                destination_warehouse=source_wh,
                date=dt.date(2026, 1, 2),
            )


def test_transfer_between_warehouses_refuses_without_source_internal_location(
    transfer_setup,
) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        empty_wh = create_warehouse(
            tenant=tenant, code="WH-EMPTY", name="Entrepot sans emplacement"
        )
        with pytest.raises(Exception, match="aucun emplacement interne"):
            transfer_between_warehouses(
                tenant=tenant,
                variant_id=variant_id,
                qty=Decimal(5),
                uom="pc",
                source_warehouse=empty_wh,
                destination_warehouse=destination_wh,
                date=dt.date(2026, 1, 2),
            )


def test_receive_warehouse_transfer_completes_transfer_to_destination_internal(
    transfer_setup,
) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(20)
        )
        departure = transfer_between_warehouses(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            source_warehouse=source_wh,
            destination_warehouse=destination_wh,
            date=dt.date(2026, 1, 2),
        )

        arrival = receive_warehouse_transfer(departure, date=dt.date(2026, 1, 5))

        assert arrival.state == StkMove.STATE_DONE
        assert arrival.location_from_id == departure.location_to_id
        assert arrival.location_to_id == destination_internal.id
        assert arrival.qty == Decimal("12.0000")

        transit_quant = get_quant(variant_id, departure.location_to)
        assert transit_quant.qty == Decimal("0.0000")
        destination_quant = get_quant(variant_id, destination_internal)
        assert destination_quant.qty == Decimal("12.0000")


def test_receive_warehouse_transfer_supports_partial_receipt(transfer_setup) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(20)
        )
        departure = transfer_between_warehouses(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            source_warehouse=source_wh,
            destination_warehouse=destination_wh,
            date=dt.date(2026, 1, 2),
        )

        arrival = receive_warehouse_transfer(departure, date=dt.date(2026, 1, 5), qty=Decimal(5))

        assert arrival.qty == Decimal("5.0000")
        transit_quant = get_quant(variant_id, departure.location_to)
        assert transit_quant.qty == Decimal("7.0000")
        destination_quant = get_quant(variant_id, destination_internal)
        assert destination_quant.qty == Decimal("5.0000")


def test_receive_warehouse_transfer_refuses_when_qty_exceeds_available_transit_stock(
    transfer_setup,
) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(20)
        )
        departure = transfer_between_warehouses(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            source_warehouse=source_wh,
            destination_warehouse=destination_wh,
            date=dt.date(2026, 1, 2),
        )

        with pytest.raises(Exception, match="insuffisante"):
            receive_warehouse_transfer(departure, date=dt.date(2026, 1, 5), qty=Decimal(13))


def test_receive_warehouse_transfer_refuses_when_double_received(transfer_setup) -> None:
    """Garde explicite (RG-STK-10 ne couvre pas les emplacements virtuels
    comme `TYPE_TRANSIT`) : recevoir deux fois le meme transfert refuse la
    seconde fois plutot que de laisser le quant de transit passer negatif
    silencieusement."""
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(20)
        )
        departure = transfer_between_warehouses(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            source_warehouse=source_wh,
            destination_warehouse=destination_wh,
            date=dt.date(2026, 1, 2),
        )
        receive_warehouse_transfer(departure, date=dt.date(2026, 1, 5))

        with pytest.raises(Exception, match="insuffisante"):
            receive_warehouse_transfer(departure, date=dt.date(2026, 1, 6))


def test_receive_warehouse_transfer_refuses_when_source_is_not_a_transit_move(
    transfer_setup,
) -> None:
    tenant, source_wh, source_internal, destination_wh, destination_internal, supplier = (
        transfer_setup
    )
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        reception = _receive_into_source(
            tenant, supplier, source_internal, variant_id=variant_id, qty=Decimal(20)
        )
        with pytest.raises(Exception, match="transit"):
            receive_warehouse_transfer(reception, date=dt.date(2026, 1, 5))
