"""RG-STK-8 (reservation, ST5 du sous-sequencement `stocks` — cf. plan) :
"la quantite disponible a la vente est `qty - qty_reserved`" — jamais de
sur-reservation, liberation manuelle vs expiration de delai, origine
generique (`content_type`/`object_id`) round-trip cross-app."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.tests.factories import MrpOrderComponentFactory
from apps.sales.tests.factories import SalesOrderLineFactory
from apps.stocks.models import StkLocation, StkReservation
from apps.stocks.services.reservations import (
    DEFAULT_MAX_AGE_DAYS,
    available_to_sell,
    expire_stale_reservations,
    release_reservation,
    reserve_stock,
)
from apps.stocks.services.warehouses import create_location, create_warehouse
from apps.stocks.tests.factories import StkQuantFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def reservations_setup():
    tenant = Tenant.objects.create(code="STK-RES-T", name="Stocks Reservations Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        variant_id = uuid.uuid4()
        quant = StkQuantFactory(
            tenant=tenant,
            variant_id=variant_id,
            location=location,
            qty=Decimal("100"),
            qty_reserved=Decimal("0"),
        )
        return tenant, location, variant_id, quant


def test_reserve_stock_increments_qty_reserved(reservations_setup) -> None:
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        reservation = reserve_stock(
            tenant=tenant, quant=quant, qty=Decimal("30"), date=dt.date(2026, 1, 1)
        )
        quant.refresh_from_db()
        assert reservation.state == StkReservation.STATE_ACTIVE
        assert reservation.qty == Decimal("30")
        assert quant.qty_reserved == Decimal("30")
        assert reservation.content_type_id is None
        assert reservation.object_id == ""


def test_reserve_stock_refuses_over_reservation(reservations_setup) -> None:
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        reserve_stock(tenant=tenant, quant=quant, qty=Decimal("80"), date=dt.date(2026, 1, 1))
        with pytest.raises(ValidationError):
            reserve_stock(tenant=tenant, quant=quant, qty=Decimal("30"), date=dt.date(2026, 1, 1))
        quant.refresh_from_db()
        # La premiere reservation reste seule appliquee.
        assert quant.qty_reserved == Decimal("80")


def test_release_reservation_decrements_qty_reserved(reservations_setup) -> None:
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        reservation = reserve_stock(
            tenant=tenant, quant=quant, qty=Decimal("40"), date=dt.date(2026, 1, 1)
        )
        release_reservation(reservation, reason="Commande annulee")
        quant.refresh_from_db()
        reservation.refresh_from_db()
        assert reservation.state == StkReservation.STATE_RELEASED
        assert quant.qty_reserved == Decimal("0")


def test_release_reservation_refuses_non_active(reservations_setup) -> None:
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        reservation = reserve_stock(
            tenant=tenant, quant=quant, qty=Decimal("10"), date=dt.date(2026, 1, 1)
        )
        release_reservation(reservation)
        with pytest.raises(ValidationError):
            release_reservation(reservation)


def test_available_to_sell_reflects_reservations(reservations_setup) -> None:
    tenant, location, variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        assert available_to_sell(variant_id, location=location) == Decimal("100")
        reserve_stock(tenant=tenant, quant=quant, qty=Decimal("25"), date=dt.date(2026, 1, 1))
        assert available_to_sell(variant_id, location=location) == Decimal("75")


def test_expire_stale_reservations_ages_out_old_and_leaves_recent(reservations_setup) -> None:
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        old = reserve_stock(tenant=tenant, quant=quant, qty=Decimal("10"), date=dt.date(2026, 1, 1))
        recent = reserve_stock(
            tenant=tenant, quant=quant, qty=Decimal("15"), date=dt.date(2026, 2, 20)
        )
        as_of = dt.date(2026, 2, 28)
        assert (as_of - dt.date(2026, 1, 1)).days > DEFAULT_MAX_AGE_DAYS
        assert (as_of - dt.date(2026, 2, 20)).days < DEFAULT_MAX_AGE_DAYS

        expired_count = expire_stale_reservations(tenant, as_of=as_of)

        old.refresh_from_db()
        recent.refresh_from_db()
        quant.refresh_from_db()
        assert expired_count == 1
        assert old.state == StkReservation.STATE_EXPIRED
        assert recent.state == StkReservation.STATE_ACTIVE
        assert quant.qty_reserved == Decimal("15")


def test_reserve_stock_without_source_object_leaves_generic_fk_empty(
    reservations_setup,
) -> None:
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        reservation = reserve_stock(
            tenant=tenant, quant=quant, qty=Decimal("5"), date=dt.date(2026, 1, 1)
        )
        assert reservation.content_type_id is None
        assert reservation.object_id == ""
        assert reservation.content_object is None


def test_reserve_stock_with_sales_order_line_source_object_round_trips(
    reservations_setup,
) -> None:
    """Origine generique cross-app (RG-STK-8) : une `SalesOrderLine` REELLE
    de `apps.sales` (jamais importee ailleurs dans `stocks` lui-meme, cf.
    regle de couplage n°1 — seul ce test, hors du perimetre applicatif de
    `stocks`, construit une instance concrete pour verifier le round-trip
    du `content_type`/`object_id` generique)."""
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        order_line = SalesOrderLineFactory(tenant=tenant)
        reservation = reserve_stock(
            tenant=tenant,
            quant=quant,
            qty=Decimal("5"),
            date=dt.date(2026, 1, 1),
            source_object=order_line,
        )
        assert reservation.object_id == str(order_line.id)
        assert reservation.content_object == order_line


def test_reserve_stock_with_mrp_order_component_source_object_round_trips(
    reservations_setup,
) -> None:
    """Meme round-trip generique que le test precedent, avec un
    `MrpOrderComponent` (l'autre origine possible citee par RG-STK-8)."""
    tenant, _location, _variant_id, quant = reservations_setup
    with use_tenant(tenant.id):
        component = MrpOrderComponentFactory(tenant=tenant)
        reservation = reserve_stock(
            tenant=tenant,
            quant=quant,
            qty=Decimal("5"),
            date=dt.date(2026, 1, 1),
            source_object=component,
        )
        assert reservation.object_id == str(component.id)
        assert reservation.content_object == component
