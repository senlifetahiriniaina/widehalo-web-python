from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import (
    MrpBom,
    MrpOperation,
    MrpOrder,
    MrpRouting,
    MrpRoutingStep,
    MrpWorkcenter,
    MrpWorkshop,
)
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.costing import (
    check_material_reconciliation,
    compute_planned_cost,
    compute_real_cost,
    consume_component,
    simulate_bom_cost,
)
from apps.mrp.services.cra import create_cra, submit_cra, validate_cra
from apps.mrp.services.orders import (
    close_order,
    confirm_order,
    create_order,
    create_work_order,
    done_work_order,
    finish_order,
    receive_from_subcontractor,
    reserve_order,
    send_to_quality_control,
    send_to_subcontractor,
    start_order,
    start_work_order,
)
from apps.stocks.tests.factories import (
    StkLocationFactory,
    StkQuantFactory,
    StkValuationLayerFactory,
    StkWarehouseFactory,
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


def test_consume_component_refuses_on_closed_order(costing_setup) -> None:
    """Bloc C, C4/PRD-10 : meme garde que
    `transformation.record_component_consumption` sur cette seconde
    fonction de declaration de consommation (jamais appelee en production
    aujourd'hui, mais atteignable par appel direct de l'API — PRD-10)."""
    tenant, _user, order, _work_order, _component_id = costing_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        order.state = MrpOrder.STATE_CLOSED
        order.save(update_fields=["state"])

        with pytest.raises(ValidationError, match="clôturé"):
            consume_component(component, qty_consumed=Decimal(21))


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


# ---------------------------------------------------------------------------
# Bloc C, C3 : close_order calcule desormais le cout reel automatiquement
# au CUMP courant + replie le cout de sous-traitance ; check_material_
# reconciliation (PRD-7, nomenclature de type process uniquement).
# ---------------------------------------------------------------------------


@pytest.fixture
def real_cost_close_setup():
    """Ordre confirme/reserve/demarre/en controle qualite, pret pour
    `finish_order`+`close_order` — composant a `variant_id` reel couvert
    par une couche de valorisation active (CUMP = 500 Ar/unite)."""
    tenant = Tenant.objects.create(code="MRP-RCOST", name="MRP Real Cost Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rcost@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-RC", name="Atelier")
        component_template_id = uuid.uuid4()
        component_variant_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-RC", product_template_id=uuid.uuid4())
        add_bom_line(
            bom,
            component_template_id=component_template_id,
            component_variant_id=component_variant_id,
            qty=Decimal(2),
        )
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        StkValuationLayerFactory(
            tenant=tenant,
            variant_id=component_variant_id,
            qty=Decimal(100),
            remaining_qty=Decimal(100),
            value_mga=Decimal(50000),
            remaining_value_mga=Decimal(50000),
        )
        confirm_order(order, user)
        reserve_order(order, user)
        start_order(order, user)
        send_to_quality_control(order, user)
        return tenant, user, order


def test_close_order_computes_real_cost_from_cump_automatically(real_cost_close_setup) -> None:
    tenant, user, order = real_cost_close_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        # qty_planned = 2 * 10 = 20.
        consume_component(component, qty_consumed=Decimal(20))
        finish_order(order, user, qty_produced=Decimal(10))
        closed = close_order(order, user)

        # material = 20 (qty_consumed) * 500 (CUMP) = 10000 ; aucun
        # travail/CRA valide dans ce setup -> labor/overhead nuls.
        assert closed.cost_material_mga == Decimal(10000)
        assert closed.cost_total_mga == Decimal(10000)
        assert closed.cost_subcontracting_mga == Decimal(0)


def test_close_order_folds_in_subcontracting_cost(real_cost_close_setup) -> None:
    tenant, user, order = real_cost_close_setup
    with use_tenant(tenant.id):
        warehouse = StkWarehouseFactory(tenant=tenant)
        order.workshop.warehouse_id = warehouse.id
        order.workshop.save(update_fields=["warehouse_id"])
        location = StkLocationFactory(tenant=tenant, warehouse=warehouse)
        sub_variant_id = uuid.uuid4()
        StkQuantFactory(tenant=tenant, variant_id=sub_variant_id, location=location, qty=Decimal(5))

        subcontract = send_to_subcontractor(
            order, partner_id=uuid.uuid4(), variant_id=sub_variant_id,
            qty=Decimal(5), price_unit=Decimal(2000),
        )
        receive_from_subcontractor(subcontract, qty_received=Decimal(5))

        component = order.components.first()
        consume_component(component, qty_consumed=Decimal(20))
        finish_order(order, user, qty_produced=Decimal(10))
        closed = close_order(order, user)

        # sous-traitance : 5 (qty_received) * 2000 (price_unit) = 10000.
        assert closed.cost_subcontracting_mga == Decimal(10000)
        # material (10000, cf. test precedent) + sous-traitance (10000).
        assert closed.cost_total_mga == Decimal(20000)


@pytest.fixture
def process_bom_setup():
    tenant = Tenant.objects.create(code="MRP-PROC", name="MRP Process Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="proc@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-PR", name="Atelier")
        component_id = uuid.uuid4()
        bom = create_bom(
            tenant=tenant, code="BOM-PROC", product_template_id=uuid.uuid4(),
            type=MrpBom.TYPE_PROCESS,
        )
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(1))
        bom.expected_yield_pct = Decimal(80)
        bom.save(update_fields=["expected_yield_pct"])
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(100))
        confirm_order(order, user)
        return tenant, user, order


def test_check_material_reconciliation_is_none_outside_process_bom(costing_setup) -> None:
    tenant, _user, order, _work_order, _component_id = costing_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        component.qty_consumed = Decimal(20)
        component.save(update_fields=["qty_consumed"])
        assert check_material_reconciliation(order) is None


def test_check_material_reconciliation_is_none_without_material_engaged(
    process_bom_setup,
) -> None:
    tenant, _user, order = process_bom_setup
    with use_tenant(tenant.id):
        assert check_material_reconciliation(order) is None


def test_check_material_reconciliation_within_threshold_needs_no_reason(
    process_bom_setup,
) -> None:
    tenant, _user, order = process_bom_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        component.qty_consumed = Decimal(100)
        component.save(update_fields=["qty_consumed"])
        # expected_output = 100 * 80% = 80. actual = 82 -> 2.5% ecart, tolere.
        order.qty_produced = Decimal(82)
        order.save(update_fields=["qty_produced"])

        result = check_material_reconciliation(order)
        assert result is not None
        assert result["material_engaged"] == Decimal(100)
        assert result["expected_output"] == Decimal(80)
        assert result["variance_pct"] == Decimal("2.5")


def test_check_material_reconciliation_beyond_threshold_requires_reason(
    process_bom_setup,
) -> None:
    tenant, _user, order = process_bom_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        component.qty_consumed = Decimal(100)
        component.save(update_fields=["qty_consumed"])
        # expected_output = 80, actual = 60 -> 25% ecart, motif requis.
        order.qty_produced = Decimal(60)
        order.save(update_fields=["qty_produced"])

        with pytest.raises(ValidationError):
            check_material_reconciliation(order)

        result = check_material_reconciliation(order, reason="Sechage plus long que prevu")
        assert result is not None
        order.refresh_from_db()
        assert order.material_reconciliation_reason == "Sechage plus long que prevu"


def test_check_material_reconciliation_counts_scrapped_qty_as_output(process_bom_setup) -> None:
    """Le rebut fait partie de la matiere "sortie", pas seulement le
    produit bon — qty_produced + qty_scrapped, jamais qty_produced seul."""
    tenant, _user, order = process_bom_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        component.qty_consumed = Decimal(100)
        component.save(update_fields=["qty_consumed"])
        order.qty_produced = Decimal(70)
        order.qty_scrapped = Decimal(12)
        order.save(update_fields=["qty_produced", "qty_scrapped"])

        # actual_output = 82, expected_output = 80 -> 2.5%, tolere.
        result = check_material_reconciliation(order)
        assert result is not None
        assert result["actual_output"] == Decimal(82)


def test_close_order_requires_reconciliation_reason_beyond_threshold(process_bom_setup) -> None:
    tenant, user, order = process_bom_setup
    with use_tenant(tenant.id):
        reserve_order(order, user)
        start_order(order, user)
        send_to_quality_control(order, user)
        component = order.components.first()
        consume_component(component, qty_consumed=Decimal(100))
        finish_order(order, user, qty_produced=Decimal(60))

        with pytest.raises(ValidationError):
            close_order(order, user)

        # `close_order` est desormais @transaction.atomic (aucun etat
        # partiel persiste en base apres le refus) — mais l'objet Python
        # en memoire garde la mutation FSM tentee par django-fsm avant le
        # rollback, d'ou le refresh explicite avant de reessayer.
        order.refresh_from_db()
        assert order.state == MrpOrder.STATE_DONE

        closed = close_order(order, user, reconciliation_reason="Sechage plus long que prevu")
        assert closed.state == MrpOrder.STATE_CLOSED
        assert closed.material_reconciliation_reason == "Sechage plus long que prevu"
