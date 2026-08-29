from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import (
    MrpOperation,
    MrpOrder,
    MrpRouting,
    MrpRoutingStep,
    MrpWorkcenter,
    MrpWorkshop,
)
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.costing import (
    compute_planned_cost,
    compute_real_cost,
    consume_component,
    simulate_bom_cost,
)
from apps.mrp.services.cra import create_cra, submit_cra, validate_cra
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
    tenant, user, order, work_order, component_id = costing_setup
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

        cra = create_cra(
            tenant=tenant,
            employee=user,
            workshop=order.workshop,
            date=order.created_at.date(),
            hours=Decimal(2),
            work_order=work_order,
            order=order,
        )
        submit_cra(cra, user)
        validate_cra(cra, user)

        costs = compute_real_cost(
            order, component_unit_costs={component_id: Decimal(1000)}, overhead_rate_pct=Decimal(10)
        )
        assert costs["material"] == Decimal(21000)
        assert costs["variance_material"] == Decimal(1000)
        # 2h de CRA valide x 6000 Ar/h = 12000 Ar de facon reelle
        assert costs["labor"] == Decimal(12000)


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


def test_simulate_bom_cost_reuses_explode_and_costing_formula() -> None:
    """La matiere reutilise EXACTEMENT `bom.explode()` (RG-MRP-2/3/4) — pour
    `qty=10`, ligne `qty=2` : `explode()` renvoie une quantite planifiee de
    `2 * 10 = 20` (meme formule que `_explode_level`), soit un cout matiere
    de `20 * 1000 = 20000`, identique a ce que produirait un `MrpOrder` reel
    confirme avec la meme BOM/quantite (cf. `test_planned_cost_computes_
    material_labor_overhead`, meme ligne `qty=2`, ordre `qty=10`).

    Le cout facon simule (gamme 120 min pour `bom.qty=1`, mis a l'echelle a
    `qty=10` -> 1200 min = 20h a 6000 Ar/h) suit la MEME structure de calcul
    que `_labor_cost` (heures x `cost_per_hour_mga`) mais n'egale pas
    necessairement le cout facon d'un ordre reel : `MrpWorkOrder.
    duration_planned_min` y est saisi manuellement a la creation de l'OF
    (cf. `orders.create_work_order`), jamais derive automatiquement de la
    gamme — difference assumee et documentee dans `costing.py`, la
    simulation n'ayant justement pas d'OF reel a partir duquel lire une
    duree saisie."""
    tenant = Tenant.objects.create(code="MRP-SIM", name="MRP Simulation Tenant")
    with use_tenant(tenant.id):
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
            cost_per_hour_mga=Decimal(6000),
        )
        operation = MrpOperation.objects.create(
            tenant=tenant,
            code="OP-COUTURE",
            name="Assemblage",
            workcenter_type=MrpWorkcenter.TYPE_SEWING,
        )
        routing = MrpRouting.objects.create(tenant=tenant, code="RTG-SIM", name="Gamme simulation")
        MrpRoutingStep.objects.create(
            tenant=tenant,
            routing=routing,
            sequence=1,
            operation=operation,
            workcenter=workcenter,
            duration_min=120,
        )
        component_id = uuid.uuid4()
        bom = create_bom(
            tenant=tenant, code="BOM-SIM", product_template_id=uuid.uuid4(), routing=routing
        )
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(2))
        activate_bom(bom)

        costs = simulate_bom_cost(
            bom,
            Decimal(10),
            component_unit_costs={component_id: Decimal(1000)},
            overhead_rate_pct=Decimal(10),
        )
        assert costs["material"] == Decimal(20000)
        # 120 min (gamme, pour bom.qty=1) * (qty=10 / bom.qty=1) = 1200 min
        # = 20h * 6000 Ar/h = 120000 Ar de facon simulee.
        assert costs["labor"] == Decimal(120000)
        assert costs["overhead"] == Decimal(12000)
        assert costs["total"] == Decimal(152000)


def test_simulate_bom_cost_does_not_persist_anything() -> None:
    """RG explicite du chantier FEA1-3 : une simulation ne cree JAMAIS
    d'ordre de fabrication reel (ni composant, ni ordre de travail) —
    seul un dict de `Decimal` en resulte."""
    tenant = Tenant.objects.create(code="MRP-SIM2", name="MRP Simulation Tenant 2")
    with use_tenant(tenant.id):
        component_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-SIM2", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(3))
        activate_bom(bom)

        orders_before = MrpOrder.objects.count()
        costs = simulate_bom_cost(
            bom,
            Decimal(5),
            component_unit_costs={component_id: Decimal(500)},
            overhead_rate_pct=Decimal(0),
        )
        assert costs["material"] == Decimal(7500)
        assert costs["labor"] == Decimal(0)
        assert costs["total"] == Decimal(7500)
        assert MrpOrder.objects.count() == orders_before
