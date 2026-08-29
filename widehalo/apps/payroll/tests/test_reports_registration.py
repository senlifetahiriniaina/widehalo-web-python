"""§5.11 reporting, REP4 : PAY-BULL enregistre dans le registre partage et
archive via `apps.reporting.services.public.render_and_archive` (RPT-10)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.services.employees import create_employee

pytestmark = pytest.mark.django_db


@pytest.fixture
def computed_payslip():
    tenant = Tenant.objects.create(code="PAY-RPT-REG", name="Payroll Reporting Reg Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        user = User.objects.create_user(
            email="pay-rpt-reg@example.com", password="Str0ngPassw0rd!23"
        )
        employee = create_employee(
            tenant, first_name="A", last_name="Employee", hire_date=dt.date(2024, 1, 1), user=user
        )
        contract = make_active_contract(
            tenant, employee_id=employee.id, wage_base=Decimal("800000")
        )
        period = make_period(tenant)
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee.id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
    return tenant, user, payslip


def test_pay_bull_is_registered() -> None:
    report = get_registered_report("PAY-BULL")
    assert report is not None
    assert report.module == "payroll"
    assert report.is_legal_document
    assert report.supports_pdf()


def test_pay_bull_render_pdf_archives_once(computed_payslip) -> None:
    tenant, user, payslip = computed_payslip
    report = get_registered_report("PAY-BULL")
    assert report is not None and report.render_pdf is not None

    with use_tenant(tenant.id):
        first = report.render_pdf({"object_id": str(payslip.id)}, user)
        second = report.render_pdf({"object_id": str(payslip.id)}, user)
        assert first == second
        assert first.startswith(b"%PDF")
        assert Document.objects.filter(object_id=str(payslip.id)).count() == 1
