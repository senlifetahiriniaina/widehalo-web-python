from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.costing import compute_planned_cost, compute_real_cost
from apps.mrp.services.interventions import declare_scrap
from apps.mrp.services.orders import confirm_order, create_order, create_work_order, done_work_order
from apps.mrp.services.reports import cost_report, efficiency_report, order_pdf, scrap_report

pytestmark = pytest.mark.django_db


@pytest.fixture
def report_setup():
    tenant = Tenant.objects.create(code="MRP-RPT", name="MRP Report Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rpt@example.com", password="Str0ngPassw0rd!23")
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
        add_bom_line(bom, component_template_id=component_id, qty=Decimal(1))
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        confirm_order(order, user)
        return tenant, user, workshop, workcenter, order


def test_order_pdf_is_generated(report_setup) -> None:
    tenant, _user, _workshop, _workcenter, order = report_setup
    with use_tenant(tenant.id):
        pdf_bytes = order_pdf(order)
        assert pdf_bytes.startswith(b"%PDF")


def test_cost_report_exposes_variances(report_setup) -> None:
    tenant, _user, _workshop, _workcenter, order = report_setup
    with use_tenant(tenant.id):
        compute_planned_cost(order, component_unit_costs={}, overhead_rate_pct=Decimal(10))
        compute_real_cost(order, component_unit_costs={}, overhead_rate_pct=Decimal(10))
        report = cost_report(order)
        assert report["reference"] == order.reference
        assert "total_variance" in report


def test_efficiency_report_computes_percentage(report_setup) -> None:
    tenant, _user, _workshop, workcenter, order = report_setup
    with use_tenant(tenant.id):
        work_order = create_work_order(order, workcenter=workcenter, qty_planned=Decimal(10))
        done_work_order(work_order, qty_done=Decimal(8), qty_rejected=Decimal(2))

        rows = efficiency_report(workcenter.code)
        assert rows[0]["efficiency_pct"] == Decimal(80)


def test_scrap_report_groups_by_reason(report_setup) -> None:
    tenant, user, _workshop, _workcenter, order = report_setup
    with use_tenant(tenant.id):
        declare_scrap(order, declared_by=user, qty=Decimal(3), reason="Defaut de coupe")
        rows = scrap_report(date_from=datetime.date.today(), date_to=datetime.date.today())
        assert rows[0]["reason"] == "Defaut de coupe"
        assert rows[0]["total_qty"] == Decimal(3)
