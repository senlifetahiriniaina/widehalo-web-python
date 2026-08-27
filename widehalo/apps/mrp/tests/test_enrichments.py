from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBomLineState, MrpWorkcenter, MrpWorkshop
from apps.mrp.services.analysis import find_shared_components, where_used
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.interventions import create_cri
from apps.mrp.services.maintenance import (
    compute_mtbf_mttr,
    create_maintenance_plan,
    plans_due,
    record_maintenance_done,
)
from apps.mrp.services.orders import confirm_order, create_order, create_work_order, done_work_order
from apps.mrp.services.procurement import (
    approve,
    consume,
    declare_shortage,
    evaluate_sample,
    get_or_create_procurement_state,
    receive,
    reject,
    request_sample,
    send_to_quality_control,
    start_production,
    validate_supplier,
)
from apps.mrp.services.procurement import (
    order as order_procurement,
)
from apps.mrp.services.quality import first_pass_yield, pareto_defect_causes
from apps.mrp.services.suppliers import (
    decide_sample,
    evaluate_supplier,
    is_supplier_approved,
    receive_sample,
)
from apps.mrp.services.suppliers import (
    request_sample as request_sample_from_supplier,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def enrichment_setup():
    tenant = Tenant.objects.create(code="MRP-ENR", name="MRP Enrichment Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="qual@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        return tenant, user, workshop, workcenter


def test_procurement_fsm_happy_path(enrichment_setup) -> None:
    tenant, user, workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)
        mrp_order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(5))
        confirm_order(mrp_order, user)
        component = mrp_order.components.first()

        state = get_or_create_procurement_state(component)
        assert state.state == MrpBomLineState.STATE_TO_ORDER

        request_sample(state, user)
        evaluate_sample(state, user)
        validate_supplier(state, user)
        order_procurement(state, user)
        receive(state, user)
        send_to_quality_control(state, user)
        approved = approve(state, user)
        assert approved.state == MrpBomLineState.STATE_AVAILABLE

        start_production(approved, user)
        consumed = consume(approved, user)
        assert consumed.state == MrpBomLineState.STATE_CONSUMED


def _procurement_state(enrichment_setup, user):
    tenant, _user, workshop, _workcenter = enrichment_setup
    bom = create_bom(tenant=tenant, code="BOM-EDGE", product_template_id=uuid.uuid4())
    add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
    activate_bom(bom)
    mrp_order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(5))
    confirm_order(mrp_order, user)
    component = mrp_order.components.first()
    return get_or_create_procurement_state(component)


def test_procurement_validate_supplier_directly_from_to_order(enrichment_setup) -> None:
    """Arete `to_order -> supplier_validated` (source alternative de
    `validate_supplier`, sans passer par l'echantillon) — distincte de
    `sample_evaluated -> supplier_validated` deja couverte par le chemin
    heureux."""
    tenant, user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        state = _procurement_state(enrichment_setup, user)
        assert state.state == MrpBomLineState.STATE_TO_ORDER
        validated = validate_supplier(state, user)
        assert validated.state == MrpBomLineState.STATE_SUPPLIER_VALIDATED


def test_procurement_declare_shortage(enrichment_setup) -> None:
    """Arete `ordered -> shortage`."""
    tenant, user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        state = _procurement_state(enrichment_setup, user)
        validate_supplier(state, user)
        order_procurement(state, user)
        shortage = declare_shortage(state, user)
        assert shortage.state == MrpBomLineState.STATE_SHORTAGE


def test_procurement_reject_after_quality_control(enrichment_setup) -> None:
    """Arete `quality_control -> rejected`."""
    tenant, user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        state = _procurement_state(enrichment_setup, user)
        validate_supplier(state, user)
        order_procurement(state, user)
        receive(state, user)
        send_to_quality_control(state, user)
        rejected = reject(state, user)
        assert rejected.state == MrpBomLineState.STATE_REJECTED


def test_procurement_forbidden_transition_consume_before_production(enrichment_setup) -> None:
    """Transition interdite representative du graphe `MrpBomLineState.state` :
    on ne peut pas consommer un composant qui n'est meme pas encore
    disponible (`to_order`)."""
    tenant, user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        state = _procurement_state(enrichment_setup, user)
        with pytest.raises(TransitionPermissionError):
            consume(state, user)


def test_supplier_evaluation_weighted_score(enrichment_setup) -> None:
    tenant, _user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        evaluation = evaluate_supplier(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=datetime.date.today(),
            score_quantity=Decimal(5),
            score_quality=Decimal(5),
            score_cost=Decimal(5),
            score_delay=Decimal(5),
            score_conformity=Decimal(5),
        )
        # Toutes les notes maximales -> score pondere = 100.
        assert evaluation.weighted_score == Decimal(100)
        assert is_supplier_approved(evaluation)


def test_supplier_conformity_blocks_regardless_of_score(enrichment_setup) -> None:
    tenant, _user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        evaluation = evaluate_supplier(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=datetime.date.today(),
            score_quantity=Decimal(5),
            score_quality=Decimal(5),
            score_cost=Decimal(5),
            score_delay=Decimal(5),
            score_conformity=Decimal(0),
            conformity_blocking=True,
        )
        assert not is_supplier_approved(evaluation)


def test_sample_request_round_trip(enrichment_setup) -> None:
    tenant, _user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        sample = request_sample_from_supplier(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            component_template_id=uuid.uuid4(),
            date_requested=datetime.date.today(),
        )
        received = receive_sample(sample, date_received=datetime.date.today())
        decided = decide_sample(received, approved=True, notes="Toucher conforme")
        assert decided.state == "approved"


def test_find_shared_components_across_active_boms(enrichment_setup) -> None:
    tenant, _user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        shared_component = uuid.uuid4()
        bom_a = create_bom(tenant=tenant, code="BOM-A", product_template_id=uuid.uuid4())
        add_bom_line(bom_a, component_template_id=shared_component, qty=Decimal(1))
        activate_bom(bom_a)
        bom_b = create_bom(tenant=tenant, code="BOM-B", product_template_id=uuid.uuid4())
        add_bom_line(bom_b, component_template_id=shared_component, qty=Decimal(1))
        activate_bom(bom_b)

        shared = find_shared_components(tenant)
        assert len(shared) == 1
        assert shared[0]["component_template_id"] == shared_component
        assert len(shared[0]["used_in_products"]) == 2


def test_where_used_finds_top_level_products(enrichment_setup) -> None:
    tenant, _user, _workshop, _workcenter = enrichment_setup
    with use_tenant(tenant.id):
        leaf = uuid.uuid4()
        mid_product = uuid.uuid4()
        top_product = uuid.uuid4()

        bom_mid = create_bom(tenant=tenant, code="BOM-MID", product_template_id=mid_product)
        add_bom_line(bom_mid, component_template_id=leaf, qty=Decimal(1))
        activate_bom(bom_mid)

        bom_top = create_bom(tenant=tenant, code="BOM-TOP", product_template_id=top_product)
        add_bom_line(bom_top, component_template_id=mid_product, qty=Decimal(1))
        activate_bom(bom_top)

        affected = where_used(tenant, leaf)
        assert set(affected) == {mid_product, top_product}


def test_first_pass_yield_computation(enrichment_setup) -> None:
    tenant, user, workshop, workcenter = enrichment_setup
    with use_tenant(tenant.id):
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)
        mrp_order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        confirm_order(mrp_order, user)
        work_order = create_work_order(mrp_order, workcenter=workcenter, qty_planned=Decimal(10))
        done_work_order(work_order, qty_done=Decimal(9), qty_rejected=Decimal(1))

        fpy = first_pass_yield(mrp_order)
        assert fpy == Decimal(90)


def test_pareto_defect_causes_orders_by_frequency(enrichment_setup) -> None:
    tenant, user, _workshop, workcenter = enrichment_setup
    with use_tenant(tenant.id):
        for _ in range(3):
            create_cri(
                tenant=tenant,
                type="incident_qualite",
                workcenter=workcenter,
                date=datetime.date.today(),
                cause="Couture lachee",
            )
        create_cri(
            tenant=tenant,
            type="incident_qualite",
            workcenter=workcenter,
            date=datetime.date.today(),
            cause="Tache tissu",
        )

        pareto = pareto_defect_causes(workshop=workcenter.workshop)
        assert pareto[0]["cause"] == "Couture lachee"
        assert pareto[0]["count"] == 3


def test_maintenance_plan_due_and_recorded(enrichment_setup) -> None:
    tenant, _user, _workshop, workcenter = enrichment_setup
    with use_tenant(tenant.id):
        plan = create_maintenance_plan(
            workcenter=workcenter, name="Graissage mensuel", interval_days=30
        )
        plan.next_due_at = datetime.date.today()
        plan.save(update_fields=["next_due_at"])

        due = plans_due(on_date=datetime.date.today())
        assert plan in due

        updated = record_maintenance_done(plan, date=datetime.date.today())
        assert updated.next_due_at == datetime.date.today() + datetime.timedelta(days=30)


def test_mtbf_mttr_from_breakdown_cri(enrichment_setup) -> None:
    tenant, _user, _workshop, workcenter = enrichment_setup
    with use_tenant(tenant.id):
        create_cri(
            tenant=tenant,
            type="panne",
            workcenter=workcenter,
            date=datetime.date(2026, 1, 1),
            downtime_min=30,
        )
        create_cri(
            tenant=tenant,
            type="panne",
            workcenter=workcenter,
            date=datetime.date(2026, 1, 11),
            downtime_min=60,
        )

        result = compute_mtbf_mttr(workcenter)
        assert result["mtbf_days"] == Decimal(10)
        assert result["mttr_minutes"] == Decimal(45)
