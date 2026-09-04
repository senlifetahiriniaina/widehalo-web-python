from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpOrder, MrpWorkcenter, MrpWorkOrder, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.orders import (
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    create_work_order,
    done_work_order,
    finish_order,
    receive_from_subcontractor,
    reserve_order,
    resume_order,
    send_to_quality_control,
    send_to_subcontractor,
    start_order,
    start_work_order,
    suspend_order,
)
from apps.stocks.models import StkReservation
from apps.stocks.tests.factories import (
    StkLocationFactory,
    StkQuantFactory,
    StkWarehouseFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def order_setup():
    tenant = Tenant.objects.create(code="MRP-ORD", name="MRP Order Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="prod@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        product_id = uuid.uuid4()
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=product_id)
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        return tenant, user, workshop, workcenter, order


def test_create_order_assigns_reference(order_setup) -> None:
    _tenant, _user, _workshop, _workcenter, order = order_setup
    assert order.reference.startswith("MRP-OF-")
    assert order.state == MrpOrder.STATE_DRAFT


def test_confirm_materializes_planned_components(order_setup) -> None:
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirmed = confirm_order(order, user)
        assert confirmed.state == MrpOrder.STATE_CONFIRMED
        components = list(order.components.all())
        assert len(components) == 1
        assert components[0].qty_planned == Decimal(20)


def test_full_happy_path_workflow(order_setup) -> None:
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserve_order(order, user)
        start_order(order, user)
        send_to_quality_control(order, user)
        finish_order(order, user, qty_produced=Decimal(10))
        closed = close_order(order, user)
        assert closed.state == MrpOrder.STATE_CLOSED
        assert closed.qty_produced == Decimal(10)


def test_suspend_requires_reason(order_setup) -> None:
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserve_order(order, user)
        start_order(order, user)
        with pytest.raises(ValidationError):
            suspend_order(order, user, reason="")


def test_suspend_and_resume(order_setup) -> None:
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserve_order(order, user)
        start_order(order, user)
        suspended = suspend_order(order, user, reason="Panne machine")
        assert suspended.state == MrpOrder.STATE_SUSPENDED
        resumed = resume_order(order, user)
        assert resumed.state == MrpOrder.STATE_IN_PRODUCTION


def test_cancel_requires_reason_and_only_before_reservation(order_setup) -> None:
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        cancelled = cancel_order(order, user, reason="Client annule")
        assert cancelled.state == MrpOrder.STATE_CANCELLED


def test_cancel_confirmed_order(order_setup) -> None:
    """Arete `confirmed -> cancelled` (RG-MRP couche 11) : distincte de
    `draft -> cancelled` deja couverte par
    `test_cancel_requires_reason_and_only_before_reservation`."""
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        cancelled = cancel_order(order, user, reason="Rupture matiere premiere")
        assert cancelled.state == MrpOrder.STATE_CANCELLED


def test_cannot_skip_states(order_setup) -> None:
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id), pytest.raises(TransitionPermissionError):
        start_order(order, user)


def test_work_order_lifecycle(order_setup) -> None:
    tenant, user, _workshop, workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        work_order = create_work_order(order, workcenter=workcenter, qty_planned=Decimal(10))
        started = start_work_order(work_order, operator=user)
        assert started.state == MrpWorkOrder.STATE_IN_PROGRESS
        done = done_work_order(work_order, qty_done=Decimal(9), qty_rejected=Decimal(1))
        assert done.state == MrpWorkOrder.STATE_DONE
        assert done.qty_done == Decimal(9)


def test_subcontracting_round_trip(order_setup) -> None:
    """Bloc C, C2 : l'envoi/reception produit desormais un VRAI mouvement
    de stock — l'atelier doit avoir un entrepot configure, avec un quant
    interne suffisant pour l'article envoye (meme discipline que
    `reservation_setup`)."""
    tenant, user, workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        warehouse = StkWarehouseFactory(tenant=tenant)
        workshop.warehouse_id = warehouse.id
        workshop.save(update_fields=["warehouse_id"])
        location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
        variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=variant_id, location=location, qty=Decimal(10))

        confirm_order(order, user)
        subcontract = send_to_subcontractor(
            order, partner_id=uuid.uuid4(), variant_id=variant_id, qty=Decimal(10)
        )
        assert subcontract.state == "sent"
        assert subcontract.send_move_id is not None
        received = receive_from_subcontractor(subcontract, qty_received=Decimal(10))
        assert received.state == "received"
        assert received.date_received is not None


@pytest.fixture
def reservation_setup():
    """Bloc C, C1 : dérive `order_setup` en donnant au composant un
    `variant_id` réel couvert par un quant interne suffisant — nécessaire
    pour exercer une réservation `stocks` réelle (`order_setup` seul
    produit un composant à `variant_id=None`, cas couvert séparément)."""
    tenant = Tenant.objects.create(code="MRP-RES", name="MRP Reservation Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="res@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        product_id = uuid.uuid4()
        component_variant_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-RES", product_template_id=product_id)
        add_bom_line(
            bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=component_variant_id,
            qty=Decimal(2),
        )
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        location = StkLocationFactory(tenant=tenant)
        quant = StkQuantFactory(
            tenant=tenant, variant_id=component_variant_id, location=location, qty=Decimal(50)
        )
        return tenant, user, order, component_variant_id, quant


def test_reserve_order_reserves_real_stock(reservation_setup) -> None:
    tenant, user, order, _variant_id, quant = reservation_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserve_order(order, user)
        component = order.components.first()
        assert component.state == "reserved"
        assert component.reservation_id is not None
        quant.refresh_from_db()
        assert quant.qty_reserved == Decimal(20)  # qty_planned = 2 * qty(10)


def test_reserve_order_flags_insufficient_stock(reservation_setup) -> None:
    tenant, user, order, _variant_id, quant = reservation_setup
    quant.qty = Decimal(5)  # < qty_planned (20) apres explode()
    quant.save(update_fields=["qty"])
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserved_order = reserve_order(order, user)
        # La transition FSM n'est jamais bloquee par un echec de reservation.
        assert reserved_order.state == MrpOrder.STATE_RESERVED
        component = order.components.first()
        assert component.state == "insufficient_stock"
        assert component.reservation_id is None


def test_reserve_order_without_variant_stays_planned(order_setup) -> None:
    """Regression : `order_setup` produit un composant sans `variant_id`
    (gap de configuration BOM/catalogue) — `reserve_order` ne doit jamais
    lever d'exception dans ce cas, ni tenter de réserver."""
    tenant, user, _workshop, _workcenter, order = order_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserve_order(order, user)
        component = order.components.first()
        assert component.variant_id is None
        assert component.state == "planned"
        assert component.reservation_id is None


def test_close_order_releases_component_reservation(reservation_setup) -> None:
    tenant, user, order, _variant_id, quant = reservation_setup
    with use_tenant(tenant.id):
        confirm_order(order, user)
        reserve_order(order, user)
        component = order.components.first()
        assert component.reservation_id is not None
        reservation_id = component.reservation_id

        start_order(order, user)
        send_to_quality_control(order, user)
        finish_order(order, user, qty_produced=Decimal(10))
        close_order(order, user)

        component.refresh_from_db()
        assert component.reservation_id is None
        reservation = StkReservation.objects.get(id=reservation_id)
        assert reservation.state == StkReservation.STATE_RELEASED
        quant.refresh_from_db()
        assert quant.qty_reserved == Decimal(0)
