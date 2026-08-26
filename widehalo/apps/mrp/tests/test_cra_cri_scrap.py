from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpCra, MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.cra import create_cra, real_labor_cost, reject_cra, submit_cra, validate_cra
from apps.mrp.services.interventions import close_cri, create_cri, declare_scrap
from apps.mrp.services.orders import confirm_order, create_order, create_work_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def production_setup():
    tenant = Tenant.objects.create(code="MRP-CRA", name="MRP CRA Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="op@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
            cost_per_hour_mga=Decimal(6000),
        )
        bom = create_bom(tenant=tenant, code="BOM-1", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        confirm_order(order, user)
        work_order = create_work_order(order, workcenter=workcenter, qty_planned=Decimal(10))
        return tenant, user, workshop, workcenter, order, work_order


def test_cra_workflow_draft_to_validated(production_setup) -> None:
    tenant, user, workshop, _workcenter, order, work_order = production_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            employee=user,
            workshop=workshop,
            date=datetime.date.today(),
            hours=Decimal(3),
            work_order=work_order,
            order=order,
        )
        assert cra.state == MrpCra.STATE_DRAFT
        submit_cra(cra, user)
        validated = validate_cra(cra, user)
        assert validated.state == MrpCra.STATE_VALIDATED
        assert validated.validated_by_id == user.id


def test_cra_can_be_rejected(production_setup) -> None:
    tenant, user, workshop, _workcenter, order, work_order = production_setup
    with use_tenant(tenant.id):
        cra = create_cra(
            tenant=tenant,
            employee=user,
            workshop=workshop,
            date=datetime.date.today(),
            hours=Decimal(1),
            work_order=work_order,
            order=order,
        )
        submit_cra(cra, user)
        rejected = reject_cra(cra, user)
        assert rejected.state == MrpCra.STATE_REJECTED


def test_only_validated_cra_enters_real_labor_cost(production_setup) -> None:
    tenant, user, workshop, _workcenter, order, work_order = production_setup
    with use_tenant(tenant.id):
        submitted_only = create_cra(
            tenant=tenant,
            employee=user,
            workshop=workshop,
            date=datetime.date.today(),
            hours=Decimal(5),
            work_order=work_order,
            order=order,
        )
        submit_cra(submitted_only, user)

        validated_cra = create_cra(
            tenant=tenant,
            employee=user,
            workshop=workshop,
            date=datetime.date.today(),
            hours=Decimal(2),
            work_order=work_order,
            order=order,
        )
        submit_cra(validated_cra, user)
        validate_cra(validated_cra, user)

        # 2h validees x 6000 Ar/h = 12000 ; les 5h soumises-seulement ignorees
        assert real_labor_cost(order) == Decimal(12000)


def test_cri_creation_and_close(production_setup) -> None:
    tenant, user, _workshop, workcenter, order, _work_order = production_setup
    with use_tenant(tenant.id):
        cri = create_cri(
            tenant=tenant,
            type="panne",
            workcenter=workcenter,
            date=datetime.date.today(),
            order=order,
            intervenant_user=user,
            duration_min=45,
            description="Arret machine",
            cause="Courroie cassee",
            action_taken="Remplacement",
            downtime_min=45,
        )
        assert cri.reference.startswith("MRP-CRI-")
        closed = close_cri(cri)
        assert closed.state == "closed"


def test_declare_scrap_updates_order_qty_scrapped(production_setup) -> None:
    tenant, user, _workshop, _workcenter, order, _work_order = production_setup
    with use_tenant(tenant.id):
        declare_scrap(order, declared_by=user, qty=Decimal(2), reason="Defaut de coupe")
        order.refresh_from_db()
        assert order.qty_scrapped == Decimal(2)
