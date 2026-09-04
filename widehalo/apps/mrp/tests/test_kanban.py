"""T2 (L3 Textile, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
tableau atelier + First Pass Yield + chatter. Même idiome de fixture que
`test_orders.py::order_setup`."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.chatter import thread_for
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkOrder, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.orders import advance_work_order, create_order, create_work_order
from apps.mrp.services.quality import first_pass_yield

pytestmark = pytest.mark.django_db


@pytest.fixture
def kanban_setup():
    tenant = Tenant.objects.create(code="MRP-KAN", name="MRP Kanban Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="atelier@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-K", name="Atelier")
        cutting = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="CUT",
            name="Coupe",
            type=MrpWorkcenter.TYPE_CUTTING,
        )
        sewing = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="SEW",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        bom = create_bom(tenant=tenant, code="BOM-K", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        cut_wo = create_work_order(order, workcenter=cutting, qty_planned=Decimal(10), sequence=1)
        sew_wo = create_work_order(order, workcenter=sewing, qty_planned=Decimal(10), sequence=2)
        return tenant, user, order, cut_wo, sew_wo


def test_advance_work_order_starts_the_next_pending_step(kanban_setup) -> None:
    tenant, user, order, cut_wo, sew_wo = kanban_setup
    with use_tenant(tenant.id):
        cut_wo = advance_work_order(cut_wo, user, qty_done=Decimal(9), qty_rejected=Decimal(1))

        assert cut_wo.state == MrpWorkOrder.STATE_DONE
        assert cut_wo.qty_done == Decimal(9)
        sew_wo.refresh_from_db()
        assert sew_wo.state == MrpWorkOrder.STATE_IN_PROGRESS
        assert sew_wo.operator_id == user.id


def test_advance_work_order_journalizes_the_transition_in_chatter(kanban_setup) -> None:
    tenant, user, order, cut_wo, _sew_wo = kanban_setup
    with use_tenant(tenant.id):
        advance_work_order(cut_wo, user, qty_done=Decimal(10))

        thread = list(thread_for(order))
        assert len(thread) == 1
        assert "Coupe" in thread[0].body
        assert "Couture" in thread[0].body
        assert thread[0].is_note is True


def test_advance_work_order_on_last_step_notes_end_of_routing_without_starting_anything(
    kanban_setup,
) -> None:
    tenant, user, order, cut_wo, sew_wo = kanban_setup
    with use_tenant(tenant.id):
        advance_work_order(cut_wo, user, qty_done=Decimal(10))
        advance_work_order(sew_wo, user, qty_done=Decimal(10))

        thread = list(thread_for(order))
        assert "fin de gamme" in thread[-1].body


def test_advance_work_order_never_restarts_a_paused_next_step(kanban_setup) -> None:
    """L'automatisation ne doit jamais écraser une décision humaine
    explicite (ex. un opérateur a déjà mis la prochaine étape en pause)."""
    tenant, user, order, cut_wo, sew_wo = kanban_setup
    with use_tenant(tenant.id):
        sew_wo.state = MrpWorkOrder.STATE_PAUSED
        sew_wo.save(update_fields=["state"])

        advance_work_order(cut_wo, user, qty_done=Decimal(10))

        sew_wo.refresh_from_db()
        assert sew_wo.state == MrpWorkOrder.STATE_PAUSED


def test_first_pass_yield_reflects_done_and_rejected_across_work_orders(kanban_setup) -> None:
    tenant, user, order, cut_wo, sew_wo = kanban_setup
    with use_tenant(tenant.id):
        advance_work_order(cut_wo, user, qty_done=Decimal(9), qty_rejected=Decimal(1))
        advance_work_order(sew_wo, user, qty_done=Decimal(9))

        # (9 + 9) bonnes / (9 + 9 + 1) traitees = 18/19
        assert first_pass_yield(order) == (Decimal(18) / Decimal(19)) * Decimal(100)


def _kanban_client(tenant: Tenant) -> Client:
    user = User.objects.create_user(email="kanban-ui@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_kanban_view_groups_cards_by_workcenter_type(kanban_setup) -> None:
    tenant, _user, order, _cut_wo, _sew_wo = kanban_setup
    client = _kanban_client(tenant)

    response = client.get("/mrp/kanban/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Coupe" in body
    assert "Couture" in body
    assert order.reference in body or "(brouillon)" in body


def test_kanban_view_post_advances_a_card(kanban_setup) -> None:
    tenant, _user, order, cut_wo, sew_wo = kanban_setup
    client = _kanban_client(tenant)

    response = client.post(
        "/mrp/kanban/", {"work_order_id": str(cut_wo.id), "qty_done": "10", "qty_rejected": "0"}
    )
    assert response.status_code == 302

    cut_wo.refresh_from_db()
    sew_wo.refresh_from_db()
    assert cut_wo.state == MrpWorkOrder.STATE_DONE
    assert sew_wo.state == MrpWorkOrder.STATE_IN_PROGRESS
