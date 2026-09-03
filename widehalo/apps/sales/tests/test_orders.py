from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError, attempt_transition
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder
from apps.sales.services.orders import (
    add_order_line,
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    create_order_from_quotation,
    mark_delivered,
    send_order,
    start_preparation,
    unblock_order,
)
from apps.stocks.models import StkLocation, StkPicking, StkReservation
from apps.stocks.tests.factories import StkLocationFactory, StkQuantFactory, StkWarehouseFactory
from apps.sales.services.quotations import (
    accept_quotation,
    add_quotation_line,
    create_quotation,
    send_quotation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def orders_setup():
    tenant = Tenant.objects.create(code="SALES-ORD", name="Sales Order Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="sales-ord@example.com", password="Str0ngPassw0rd!23")
        partner = PartnerFactory(tenant=tenant)
        return tenant, user, partner


def test_create_order_assigns_reference(orders_setup) -> None:
    tenant, _user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        assert order.reference.startswith("CMD-")
        assert order.state == SalesOrder.STATE_DRAFT


def test_create_order_with_custom_reference_uses_it_as_is(orders_setup) -> None:
    tenant, _user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant, partner_id=partner.id, date=dt.date.today(), reference="CMD-PERSO-01"
        )
        assert order.reference == "CMD-PERSO-01"


def test_create_order_with_colliding_reference_raises(orders_setup) -> None:
    tenant, _user, partner = orders_setup
    with use_tenant(tenant.id):
        create_order(
            tenant=tenant, partner_id=partner.id, date=dt.date.today(), reference="CMD-DUP-01"
        )
        with pytest.raises(ValidationError):
            create_order(
                tenant=tenant, partner_id=partner.id, date=dt.date.today(), reference="CMD-DUP-01"
            )
        assert SalesOrder.objects.filter(reference="CMD-DUP-01").count() == 1


def test_create_order_from_quotation_copies_lines(orders_setup) -> None:
    tenant, _user, partner = orders_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_quotation_line(
            quotation,
            description="Prestation",
            qty=Decimal(2),
            unit_price=Decimal("10000"),
            is_custom=True,
        )
        with pytest.raises(ValidationError):
            create_order_from_quotation(quotation)

        send_quotation(quotation)
        accept_quotation(quotation)
        order = create_order_from_quotation(quotation)
        assert order.quotation_id == quotation.id
        assert order.partner_id == quotation.partner_id
        assert order.lines.count() == 1
        line = order.lines.first()
        assert line.description == "Prestation"
        assert line.qty == Decimal(2)
        assert line.unit_price == Decimal("10000")
        assert order.amount_total == Decimal("20000.0000")


def test_confirm_order_happy_path_within_credit_limit(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        confirmed = confirm_order(order, user)
        assert confirmed.state == SalesOrder.STATE_CONFIRMED
        assert confirmed.date_confirmed == dt.date.today()


def test_confirm_order_blocks_when_over_credit_limit(orders_setup) -> None:
    tenant, user, _partner = orders_setup
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant, credit_limit_mga=Decimal("5000"))
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(10000), is_custom=True
        )
        blocked = confirm_order(order, user)
        assert blocked.state == SalesOrder.STATE_BLOCKED
        assert blocked.blocked_reason


def test_unblock_order_returns_to_confirmed(orders_setup) -> None:
    tenant, user, _partner = orders_setup
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant, credit_limit_mga=Decimal("5000"))
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(10000), is_custom=True
        )
        confirm_order(order, user)
        assert order.state == SalesOrder.STATE_BLOCKED
        unblocked = unblock_order(order, user)
        assert unblocked.state == SalesOrder.STATE_CONFIRMED


def test_send_then_confirm(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        sent = send_order(order, user)
        assert sent.state == SalesOrder.STATE_SENT
        confirmed = confirm_order(order, user)
        assert confirmed.state == SalesOrder.STATE_CONFIRMED


def test_full_happy_path_workflow(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(5), unit_price=Decimal(1000), is_custom=True
        )
        confirm_order(order, user)
        start_preparation(order, user)
        assert order.state == SalesOrder.STATE_IN_PREPARATION
        delivered = mark_delivered(order, user)
        assert delivered.state == SalesOrder.STATE_DELIVERED
        line = order.lines.first()
        line.refresh_from_db()
        assert line.qty_delivered == line.qty


def test_partial_then_full_delivery(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(5), unit_price=Decimal(1000), is_custom=True
        )
        confirm_order(order, user)
        start_preparation(order, user)
        partial = mark_delivered(order, user, partial=True)
        assert partial.state == SalesOrder.STATE_PARTIALLY_DELIVERED
        full = mark_delivered(order, user)
        assert full.state == SalesOrder.STATE_DELIVERED


def test_mark_delivered_creates_a_real_stock_picking_for_reserved_lines(orders_setup) -> None:
    """Correctif de l'ecart confirme par l'audit
    (docs/audit/2026-09-cahier-des-charges-v3-audit.md, §6/§8) : une ligne
    "sur stock" effectivement reservee a la confirmation doit produire un
    VRAI mouvement de sortie de stock a la livraison, pas seulement
    `qty_delivered = qty`."""
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        warehouse = StkWarehouseFactory(tenant=tenant)
        internal_location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
        StkLocationFactory(tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT)
        StkQuantFactory(
            tenant=tenant, variant_id=variant_id, location=internal_location, qty=Decimal(50)
        )

        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            variant_id=variant_id,
            description="Article sur stock",
            qty=Decimal(5),
            unit_price=Decimal(1000),
        )
        confirm_order(order, user)
        line.refresh_from_db()
        assert line.stock_reservation_id is not None

        start_preparation(order, user)
        mark_delivered(order, user)

        reservation = StkReservation.objects.get(id=line.stock_reservation_id)
        assert reservation.state == StkReservation.STATE_RELEASED
        picking = StkPicking.objects.get(source_document=order.reference)
        assert picking.type == StkPicking.TYPE_SORTIE
        assert picking.state == StkPicking.STATE_DONE

        line.refresh_from_db()
        assert line.qty_delivered == line.qty


def test_mark_delivered_leaves_custom_lines_on_the_naive_path(orders_setup) -> None:
    """Une ligne hors catalogue (`is_custom`) n'a jamais de reservation —
    le comportement naif preexistant (`qty_delivered = qty` sans mouvement
    de stock) reste inchange pour ce cas, perimetre assume du correctif
    (cf. docstring `mark_delivered`)."""
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Prestation", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        confirm_order(order, user)
        start_preparation(order, user)

        delivered = mark_delivered(order, user)

        assert delivered.state == SalesOrder.STATE_DELIVERED
        assert not StkPicking.objects.filter(source_document=order.reference).exists()


def test_close_order_requires_invoiced_state(orders_setup) -> None:
    """`invoiced -> closed` est la seule arete atteinte reellement par
    `close_order` en S2 (RG-SAL-2/facturation reelle = S4) : l'arete
    `delivered -> invoiced` n'a encore aucune fonction de service qui la
    declenche, elle est donc exercee ici directement via
    `attempt_transition` pour couvrir l'arete FSM (meme patron que les
    aretes non encore cablees de `AccMove.invoice_state`)."""
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        confirm_order(order, user)
        start_preparation(order, user)
        mark_delivered(order, user)

        attempt_transition(order, "mark_invoiced", user)
        order.save(update_fields=["state"])
        assert order.state == SalesOrder.STATE_INVOICED

        closed = close_order(order, user)
        assert closed.state == SalesOrder.STATE_CLOSED


def test_cancel_requires_reason(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        with pytest.raises(ValidationError):
            cancel_order(order, user, reason="")


def test_cancel_draft_order(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        cancelled = cancel_order(order, user, reason="Client annule")
        assert cancelled.state == SalesOrder.STATE_CANCELLED
        assert cancelled.cancel_reason == "Client annule"


def test_cancel_confirmed_order(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        confirm_order(order, user)
        cancelled = cancel_order(order, user, reason="Rupture matiere premiere")
        assert cancelled.state == SalesOrder.STATE_CANCELLED


def test_cancel_in_preparation_order(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        confirm_order(order, user)
        start_preparation(order, user)
        cancelled = cancel_order(order, user, reason="Probleme fournisseur")
        assert cancelled.state == SalesOrder.STATE_CANCELLED


def test_cancel_blocked_order(orders_setup) -> None:
    tenant, user, _partner = orders_setup
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant, credit_limit_mga=Decimal("5000"))
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(10000), is_custom=True
        )
        confirm_order(order, user)
        assert order.state == SalesOrder.STATE_BLOCKED
        cancelled = cancel_order(order, user, reason="Client insolvable")
        assert cancelled.state == SalesOrder.STATE_CANCELLED


def test_cannot_cancel_delivered_order(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order, description="Article", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        confirm_order(order, user)
        start_preparation(order, user)
        mark_delivered(order, user)
        with pytest.raises(ValidationError):
            cancel_order(order, user, reason="Trop tard")


def test_cannot_skip_states(orders_setup) -> None:
    tenant, user, partner = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        with pytest.raises(TransitionPermissionError):
            start_preparation(order, user)
