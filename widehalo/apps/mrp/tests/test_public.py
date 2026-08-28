"""Tests du contrat public de `mrp` (`apps/mrp/services/public.py`) —
seule surface que `sales`/`purchase` (et les autres apps metier) ont le
droit d'importer. Couvre ici le gap ajoute pour RG-SAL-3 (S3 du
sous-sequencement `sales`, cf. plan) : `create_manufacturing_order`, le
gap ajoute pour SAL-AVCT1 (S4) : `get_order_produced_qty`, et les gaps
ajoutes pour RG-PUR-8 (PU7 du sous-sequencement `purchase`, mutualisation
MRP-QQCD1) : `record_supplier_evaluation`/`get_supplier_score`/
`list_supplier_evaluations`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpOrder, MrpSupplierEvaluation
from apps.mrp.services.bom import activate_bom, create_bom
from apps.mrp.services.public import (
    create_manufacturing_order,
    get_order_produced_qty,
    get_supplier_score,
    get_total_workshop_capacity,
    list_closed_orders,
    list_supplier_evaluations,
    record_supplier_evaluation,
)
from apps.mrp.tests.factories import MrpOrderFactory, MrpWorkshopFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_setup():
    tenant = Tenant.objects.create(code="MRP-PUB", name="MRP Public Tenant")
    with use_tenant(tenant.id):
        return tenant


def test_create_manufacturing_order_creates_real_order_when_bom_and_workshop_exist(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        product_template_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-PUB-1", product_template_id=product_template_id)
        activate_bom(bom)
        MrpWorkshopFactory(tenant=tenant)

        order_id = create_manufacturing_order(
            tenant=tenant,
            product_template_id=product_template_id,
            variant_id=variant_id,
            qty=Decimal("10"),
        )

        assert order_id is not None
        order = MrpOrder.objects.get(id=order_id)
        assert order.bom_id == bom.id
        assert order.variant_id == variant_id
        assert order.qty == Decimal("10")
        assert order.state == MrpOrder.STATE_DRAFT


def test_create_manufacturing_order_returns_none_without_active_bom(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant)
        order_id = create_manufacturing_order(
            tenant=tenant,
            product_template_id=uuid.uuid4(),
            qty=Decimal("5"),
        )
        assert order_id is None
        assert not MrpOrder.objects.exists()


def test_create_manufacturing_order_returns_none_without_workshop(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        product_template_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-PUB-2", product_template_id=product_template_id)
        activate_bom(bom)

        order_id = create_manufacturing_order(
            tenant=tenant,
            product_template_id=product_template_id,
            qty=Decimal("5"),
        )

        assert order_id is None
        assert not MrpOrder.objects.exists()


def test_get_order_produced_qty_returns_current_value(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant, qty=Decimal("10"), qty_produced=Decimal("4"))
        assert get_order_produced_qty(order.id) == Decimal("4")


def test_get_order_produced_qty_returns_none_for_unknown_order(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        assert get_order_produced_qty(uuid.uuid4()) is None


def test_list_closed_orders_returns_only_closed_orders_of_tenant(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        closed = MrpOrderFactory(
            tenant=tenant, state=MrpOrder.STATE_CLOSED, qty_produced=Decimal("7")
        )
        MrpOrderFactory(tenant=tenant, state=MrpOrder.STATE_DRAFT)

        results = list_closed_orders(tenant)

        assert len(results) == 1
        row = results[0]
        assert row["id"] == closed.id
        assert row["reference"] == closed.reference
        assert row["workshop_id"] == closed.workshop_id
        assert row["qty_produced"] == Decimal("7")
        assert row["closed_at"] == closed.updated_at.date()


def test_list_closed_orders_respects_since_window(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        old_order = MrpOrderFactory(tenant=tenant, state=MrpOrder.STATE_CLOSED)
        MrpOrder.objects.filter(id=old_order.id).update(
            updated_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        )
        recent_order = MrpOrderFactory(tenant=tenant, state=MrpOrder.STATE_CLOSED)

        results = list_closed_orders(tenant, since=dt.date(2026, 1, 1))

        result_ids = {row["id"] for row in results}
        assert recent_order.id in result_ids
        assert old_order.id not in result_ids


def test_list_closed_orders_returns_empty_list_without_closed_orders(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        MrpOrderFactory(tenant=tenant, state=MrpOrder.STATE_DRAFT)
        assert list_closed_orders(tenant) == []


def test_get_total_workshop_capacity_sums_non_subcontractor_workshops(public_setup) -> None:
    """RG-SAL-7 (S6 du sous-sequencement `sales`) : la capacite totale
    somme uniquement les ateliers non sous-traitants — meme filtre que
    `create_manufacturing_order`."""
    tenant = public_setup
    with use_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("8.00"))
        MrpWorkshopFactory(tenant=tenant, capacity_hours_day=Decimal("10.50"))
        MrpWorkshopFactory(
            tenant=tenant, capacity_hours_day=Decimal("40.00"), is_subcontractor=True
        )

        assert get_total_workshop_capacity(tenant) == Decimal("18.50")


def test_get_total_workshop_capacity_returns_zero_without_workshop(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        assert get_total_workshop_capacity(tenant) == Decimal(0)


def test_record_supplier_evaluation_delegates_to_evaluate_supplier(public_setup) -> None:
    """RG-PUR-8 : `component_template_id` reste `None` (evaluation d'un
    fournisseur dans son ensemble, pas d'un composant precis) et le calcul
    de `weighted_score` est bien celui de `evaluate_supplier` (deja
    verifie par ses propres tests) — hand-check : notes toutes a 3/5,
    poids par defaut (18+30+27+13+12=100) => weighted = (3*100)/5 = 60.00."""
    tenant = public_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        evaluation_id = record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 3, 31),
            score_quantity=Decimal("3"),
            score_quality=Decimal("3"),
            score_cost=Decimal("3"),
            score_delay=Decimal("3"),
            score_conformity=Decimal("3"),
        )
        evaluation = MrpSupplierEvaluation.objects.get(id=evaluation_id)
        assert evaluation.partner_id == partner_id
        assert evaluation.component_template_id is None
        assert evaluation.weighted_score == Decimal("60.00")


def test_get_supplier_score_returns_most_recent_weighted_score(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 1, 15),
            score_quantity=Decimal("2"),
            score_quality=Decimal("2"),
            score_cost=Decimal("2"),
            score_delay=Decimal("2"),
            score_conformity=Decimal("2"),
        )
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 4, 15),
            score_quantity=Decimal("5"),
            score_quality=Decimal("5"),
            score_cost=Decimal("5"),
            score_delay=Decimal("5"),
            score_conformity=Decimal("5"),
        )

        assert get_supplier_score(partner_id) == Decimal("100.00")


def test_get_supplier_score_respects_since_window(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 1, 15),
            score_quantity=Decimal("2"),
            score_quality=Decimal("2"),
            score_cost=Decimal("2"),
            score_delay=Decimal("2"),
            score_conformity=Decimal("2"),
        )

        assert get_supplier_score(partner_id, since=dt.date(2026, 2, 1)) is None


def test_get_supplier_score_returns_none_without_evaluation(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        assert get_supplier_score(uuid.uuid4()) is None


def test_list_supplier_evaluations_returns_primitives_most_recent_first(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 1, 15),
            score_quantity=Decimal("1"),
            score_quality=Decimal("1"),
            score_cost=Decimal("1"),
            score_delay=Decimal("1"),
            score_conformity=Decimal("1"),
        )
        record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 4, 15),
            score_quantity=Decimal("4"),
            score_quality=Decimal("4"),
            score_cost=Decimal("4"),
            score_delay=Decimal("4"),
            score_conformity=Decimal("4"),
        )

        results = list_supplier_evaluations(partner_id)
        assert len(results) == 2
        assert results[0]["date"] == dt.date(2026, 4, 15)
        assert results[1]["date"] == dt.date(2026, 1, 15)
        assert isinstance(results[0]["weighted_score"], Decimal)


def test_list_supplier_evaluations_returns_empty_list_without_evaluation(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        assert list_supplier_evaluations(uuid.uuid4()) == []
