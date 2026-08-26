from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.costing import compute_planned_cost, compute_real_cost, consume_component
from apps.mrp.services.orders import (
    confirm_order,
    create_order,
    create_work_order,
    done_work_order,
    start_work_order,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def costing_setup():
    tenant = Tenant.objects.create(code="MRP-COST", name="MRP Cost Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="cost@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
            cost_per_hour_mga=Decimal(6000),
        )
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        confirm_order(order, user)
        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=Decimal(10), duration_planned_min=120
        )
        return tenant, user, order, work_order, component_id


def test_planned_cost_computes_material_labor_overhead(costing_setup) -> None:
    tenant, _user, order, _work_order, component_id = costing_setup
    with use_tenant(tenant.id):
        costs = compute_planned_cost(
            order,
            component_unit_costs={component_id: Decimal(1000)},
            overhead_rate_pct=Decimal(10),
        )
        # 20 (qty_planned) * 1000 = 20000 matiere
        assert costs["material"] == Decimal(20000)
        # 120 min = 2h * 6000 = 12000 facon
        assert costs["labor"] == Decimal(12000)
        assert costs["overhead"] == Decimal(1200)
        assert costs["total"] == Decimal(33200)

        order.refresh_from_db()
        assert order.cost_total_planned_mga == Decimal(33200)


def test_real_cost_computes_variance_against_planned(costing_setup) -> None:
    tenant, _user, order, work_order, component_id = costing_setup
    with use_tenant(tenant.id):
        compute_planned_cost(
            order, component_unit_costs={component_id: Decimal(1000)}, overhead_rate_pct=Decimal(10)
        )

        component = order.components.first()
        consume_component(component, qty_consumed=Decimal(21))

        start_work_order(work_order)
        work_order.duration_real_min = 150
        work_order.save(update_fields=["duration_real_min"])
        done_work_order(work_order, qty_done=Decimal(10))

        costs = compute_real_cost(
            order, component_unit_costs={component_id: Decimal(1000)}, overhead_rate_pct=Decimal(10)
        )
        assert costs["material"] == Decimal(21000)
        assert costs["variance_material"] == Decimal(1000)


def test_consumption_variance_within_threshold_needs_no_reason(costing_setup) -> None:
    tenant, _user, order, _work_order, _component_id = costing_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        # qty_planned = 20, 21 = 5% ecart, tolere sans motif
        consumed = consume_component(component, qty_consumed=Decimal(21))
        assert consumed.qty_consumed == Decimal(21)


def test_consumption_variance_above_threshold_requires_reason(costing_setup) -> None:
    tenant, _user, order, _work_order, _component_id = costing_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        with pytest.raises(ValidationError):
            consume_component(component, qty_consumed=Decimal(30))

        consumed = consume_component(component, qty_consumed=Decimal(30), reason="Chute anormale")
        assert consumed.variance_reason == "Chute anormale"
