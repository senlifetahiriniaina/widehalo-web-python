"""Tests du contrat public de `stocks` (`apps/stocks/services/public.py`) —
seule surface que `logistics` (LOG5, RG-LOG-7) et, depuis ce chantier de
durcissement retroactif, `sales`/`purchase` ont le droit d'importer.
Couvre les trois gaps exposes : `apply_landed_cost_to_valuation` (deja
construit LOG5, jusqu'ici seulement exerce indirectement via
`apps.logistics.services.customs.close_customs_file`), et les deux
nouveaux gaps `check_and_reserve_stock`/`get_available_stock_qty`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkPicking, StkQuant, StkReservation
from apps.stocks.services.public import (
    apply_landed_cost_to_valuation,
    check_and_reserve_stock,
    deliver_reserved_stock,
    get_available_stock_qty,
    receive_pos_return,
    sell_from_stock,
)
from apps.stocks.tests.factories import (
    StkLocationFactory,
    StkMoveFactory,
    StkQuantFactory,
    StkValuationLayerFactory,
    StkWarehouseFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="STK-PUB", name="Stocks Public Tenant")
    with use_tenant(t.id):
        yield t


# ---------------------------------------------------------------------------
# apply_landed_cost_to_valuation (deja construit LOG5) — cf. module docstring.
# ---------------------------------------------------------------------------


def test_apply_landed_cost_to_valuation_prorates_across_active_layers(tenant) -> None:
    variant_id = uuid.uuid4()
    layer_a = StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(30),
        remaining_qty=Decimal(30),
        value_mga=Decimal("300000"),
        remaining_value_mga=Decimal("300000"),
    )
    layer_b = StkValuationLayerFactory(
        tenant=tenant,
        variant_id=variant_id,
        qty=Decimal(10),
        remaining_qty=Decimal(10),
        value_mga=Decimal("100000"),
        remaining_value_mga=Decimal("100000"),
    )

    result = apply_landed_cost_to_valuation(variant_id, additional_cost_mga=Decimal("40000"))

    assert result is True
    layer_a.refresh_from_db()
    layer_b.refresh_from_db()
    # Prorata sur remaining_qty : 30/40 et 10/40 de 40000 -> 30000 et 10000.
    assert layer_a.remaining_value_mga == Decimal("330000")
    assert layer_b.remaining_value_mga == Decimal("110000")


def test_apply_landed_cost_to_valuation_returns_false_without_active_layers(tenant) -> None:
    result = apply_landed_cost_to_valuation(uuid.uuid4(), additional_cost_mga=Decimal("10000"))
    assert result is False


# ---------------------------------------------------------------------------
# check_and_reserve_stock — gap ajoute pour lever le stub RG-SAL-3 "sur stock".
# ---------------------------------------------------------------------------


def test_check_and_reserve_stock_reserves_a_single_sufficient_quant(tenant) -> None:
    variant_id = uuid.uuid4()
    location = StkLocationFactory(tenant=tenant)
    StkQuantFactory(
        tenant=tenant,
        variant_id=variant_id,
        location=location,
        qty=Decimal(20),
        qty_reserved=Decimal(5),
    )

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(10), date=dt.date(2026, 1, 15)
    )

    assert reservation_id is not None
    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.qty == Decimal(10)
    assert reservation.state == StkReservation.STATE_ACTIVE


def test_check_and_reserve_stock_returns_none_without_a_single_sufficient_quant(tenant) -> None:
    """Deux quants de 10 chacun (20 au total) ne couvrent pas une demande
    de 15 a eux seuls — simplification assumee documentee, jamais un
    fractionnement de la reservation sur plusieurs quants."""
    variant_id = uuid.uuid4()
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(10))
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(10))

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(15), date=dt.date(2026, 1, 15)
    )

    assert reservation_id is None
    assert not StkReservation.objects.exists()


def test_check_and_reserve_stock_ignores_virtual_locations(tenant) -> None:
    variant_id = uuid.uuid4()
    virtual_location = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_FOURNISSEUR)
    StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=virtual_location, qty=Decimal(50)
    )

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(5), date=dt.date(2026, 1, 15)
    )

    assert reservation_id is None


def test_check_and_reserve_stock_records_source_object(tenant) -> None:
    variant_id = uuid.uuid4()
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(20))
    move = StkMoveFactory(tenant=tenant)

    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(5), date=dt.date(2026, 1, 15), source_object=move
    )

    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.object_id == str(move.pk)


# ---------------------------------------------------------------------------
# get_available_stock_qty — gap ajoute pour lever le stub RG-PUR-3.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# deliver_reserved_stock — correctif du gap sales.mark_delivered
# (docs/audit/2026-09-cahier-des-charges-v3-audit.md, §6/§8).
# ---------------------------------------------------------------------------


def test_deliver_reserved_stock_moves_qty_and_releases_reservation(tenant) -> None:
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    client_location = StkLocationFactory(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT
    )
    quant = StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(20)
    )
    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(7), date=dt.date(2026, 1, 15)
    )
    assert reservation_id is not None

    picking_id = deliver_reserved_stock(
        tenant, reservation_id=reservation_id, date=dt.date(2026, 1, 16), source_document="CMD-1"
    )

    picking = StkPicking.objects.get(id=picking_id)
    assert picking.type == StkPicking.TYPE_SORTIE
    assert picking.state == StkPicking.STATE_DONE
    assert picking.location_from_id == internal_location.id
    assert picking.location_to_id == client_location.id
    assert picking.source_document == "CMD-1"

    quant.refresh_from_db()
    assert quant.qty == Decimal(13)  # 20 - 7 physiquement sorties
    assert quant.qty_reserved == Decimal(0)  # reservation liberee

    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.state == StkReservation.STATE_RELEASED

    client_quant = StkQuant.objects.get(location=client_location, variant_id=variant_id)
    assert client_quant.qty == Decimal(7)  # double-entree RG-STK-1


def test_deliver_reserved_stock_raises_without_a_client_location(tenant) -> None:
    variant_id = uuid.uuid4()
    # Entrepot SANS emplacement virtuel "client" configure.
    internal_location = StkLocationFactory(tenant=tenant)
    StkQuantFactory(tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(20))
    reservation_id = check_and_reserve_stock(
        tenant, variant_id=variant_id, qty=Decimal(5), date=dt.date(2026, 1, 15)
    )
    assert reservation_id is not None

    with pytest.raises(ValidationError):
        deliver_reserved_stock(tenant, reservation_id=reservation_id, date=dt.date(2026, 1, 16))

    # La reservation reste active — rien n'a ete perdu par l'echec.
    reservation = StkReservation.objects.get(id=reservation_id)
    assert reservation.state == StkReservation.STATE_ACTIVE


def test_get_available_stock_qty_aggregates_across_internal_quants(tenant) -> None:
    variant_id = uuid.uuid4()
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(20), qty_reserved=Decimal(5))
    StkQuantFactory(tenant=tenant, variant_id=variant_id, qty=Decimal(10), qty_reserved=Decimal(0))

    assert get_available_stock_qty(variant_id) == Decimal(25)


def test_get_available_stock_qty_is_zero_for_unknown_variant(tenant) -> None:
    assert get_available_stock_qty(uuid.uuid4()) == Decimal(0)


def test_sell_from_stock_moves_qty_without_any_prior_reservation(tenant) -> None:
    """Gap ajoute pour le module `pos` (POS distribution) : a la difference
    de `check_and_reserve_stock`/`deliver_reserved_stock`, aucune
    `StkReservation` n'est jamais creee sur ce chemin."""
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    client_location = StkLocationFactory(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT
    )
    quant = StkQuantFactory(
        tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(20)
    )

    picking_id = sell_from_stock(
        tenant,
        variant_id=variant_id,
        qty=Decimal(6),
        warehouse_id=warehouse.id,
        date=dt.date(2026, 1, 15),
        source_document="TICKET-1",
    )

    picking = StkPicking.objects.get(id=picking_id)
    assert picking.type == StkPicking.TYPE_SORTIE
    assert picking.state == StkPicking.STATE_DONE
    assert picking.location_from_id == internal_location.id
    assert picking.location_to_id == client_location.id
    assert StkReservation.objects.count() == 0

    quant.refresh_from_db()
    assert quant.qty == Decimal(14)


def test_sell_from_stock_returns_none_without_enough_qty_or_a_client_location(tenant) -> None:
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    StkQuantFactory(tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(3))

    # Stock insuffisant.
    assert (
        sell_from_stock(
            tenant, variant_id=variant_id, qty=Decimal(5), warehouse_id=warehouse.id, date=dt.date(2026, 1, 15)
        )
        is None
    )
    # Aucun emplacement virtuel client configure pour cet entrepot.
    assert (
        sell_from_stock(
            tenant, variant_id=variant_id, qty=Decimal(1), warehouse_id=warehouse.id, date=dt.date(2026, 1, 15)
        )
        is None
    )


def test_receive_pos_return_puts_qty_back_into_the_first_internal_location(tenant) -> None:
    variant_id = uuid.uuid4()
    warehouse = StkWarehouseFactory(tenant=tenant)
    internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
    StkLocationFactory(tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT)

    picking_id = receive_pos_return(
        tenant,
        variant_id=variant_id,
        qty=Decimal(2),
        warehouse_id=warehouse.id,
        date=dt.date(2026, 1, 16),
        source_document="AVOIR-1",
    )

    picking = StkPicking.objects.get(id=picking_id)
    assert picking.type == StkPicking.TYPE_ENTREE
    assert picking.state == StkPicking.STATE_DONE
    assert picking.location_to_id == internal_location.id

    quant = StkQuant.objects.get(location=internal_location, variant_id=variant_id)
    assert quant.qty == Decimal(2)
