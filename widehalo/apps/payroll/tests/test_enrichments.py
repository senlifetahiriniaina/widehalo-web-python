"""Tests des enrichissements WideHalo §5.10.11 : PAY-CTRL1 (anomalies),
PAY-MM1 (mobile money), PAY-PROJ1 (projection), RG-PAY-7 (STC),
RG-PAY-9 (masquage des montants pour les roles "manager")."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.permissions import filter_fields_for_role
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.advances import approve_advance, request_advance, start_repayment
from apps.payroll.services.anomalies import detect_batch_anomalies
from apps.payroll.services.batches import create_batch
from apps.payroll.services.mobile_money import generate_mobile_money_transfer_file
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.services.projection import project_payroll_mass
from apps.payroll.services.settlement import compute_settlement
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def test_anomaly_negative_net_detected() -> None:
    tenant = Tenant.objects.create(code="PAY-CTRL", name="Controles")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("500000")
        )
        period = make_period(tenant)
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=contract.employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
        payslip.state = PayPayslip.STATE_COMPUTED
        payslip.net_to_pay = Decimal("-1000")
        payslip.save(update_fields=["state", "net_to_pay"])

        batch = create_batch(period)
        codes = {a.code for a in detect_batch_anomalies(batch)}
        assert "net_negative" in codes


def test_mobile_money_file_lists_only_mobile_money_payslips() -> None:
    tenant = Tenant.objects.create(code="PAY-MM1", name="Mobile money")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("700000")
        )
        period = make_period(tenant)
        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
            payment_method=PayPayslip.PAYMENT_MOBILE_MONEY,
        )
        compute_payslip(payslip)
        payslip.state = PayPayslip.STATE_COMPUTED
        payslip.save(update_fields=["state"])
        batch = create_batch(period)
        payslip.refresh_from_db()

        csv_content = generate_mobile_money_transfer_file(
            batch, phone_by_employee={str(employee_id): "0341234567"}
        )
        assert "0341234567" in csv_content
        assert str(payslip.net_to_pay) in csv_content


def test_projection_constant_headcount() -> None:
    tenant = Tenant.objects.create(code="PAY-PROJ1", name="Projection")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1000000"))
        make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=Decimal("500000"))

        projection = project_payroll_mass(tenant, months=3)
        assert len(projection) == 3
        assert projection[0].total_wage_base == Decimal("1500000")
        assert projection[1].total_wage_base == Decimal("1500000")


def test_projection_applies_planned_increase() -> None:
    tenant = Tenant.objects.create(code="PAY-PROJ2", name="Projection augmentation")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1000000")
        )

        projection = project_payroll_mass(
            tenant, months=6, planned_increases={f"{contract.id}:3": Decimal("1200000")}
        )
        assert projection[1].total_wage_base == Decimal("1000000")
        assert projection[2].total_wage_base == Decimal("1200000")
        assert projection[5].total_wage_base == Decimal("1200000")


def test_advance_deduction_applied_to_next_payslip() -> None:
    tenant = Tenant.objects.create(code="PAY-ADV", name="Avances")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        from apps.core.models.user import User

        user = User.objects.create_user(email="rh-adv@example.com", password="Str0ngPassw0rd!23")
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1000000")
        )
        period = make_period(tenant)

        advance = request_advance(
            tenant,
            employee_id=employee_id,
            date=period.date_from,
            amount=Decimal("300000"),
            repayment_months=3,
        )
        approve_advance(advance, user)
        start_repayment(advance, user)

        payslip = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip)
        installment_line = payslip.lines.get(code="RETENUE_AVANCE")
        assert installment_line.amount == Decimal("100000")


def test_settlement_stc_computes_leave_and_notice_indemnities() -> None:
    tenant = Tenant.objects.create(code="PAY-STC", name="STC")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant,
            employee_id=employee_id,
            wage_base=Decimal("780000"),
            date_start=dt.date(2020, 1, 1),
        )
        contract.notice_days = 30
        contract.save(update_fields=["notice_days"])

        settlement = compute_settlement(
            contract, termination_date=dt.date(2026, 3, 15), notice_worked=False
        )
        conge_line = settlement.lines.get(code="INDEMNITE_CONGE")
        preavis_line = settlement.lines.get(code="INDEMNITE_PREAVIS")
        assert preavis_line.amount == (Decimal("780000") / Decimal(26)) * Decimal(30)
        assert conge_line.amount >= 0


def test_manager_role_cannot_see_payslip_amounts() -> None:
    """RG-PAY-9 : decision de conception — `resp_production`/`chef_atelier`/
    `resp_commercial` voient l'EXISTENCE d'un bulletin mais jamais ses
    montants (`SENSITIVE_FIELDS`)."""
    data = {
        "id": "x",
        "state": "approved",
        "net_to_pay": Decimal("1000000"),
        "gross": Decimal("1200000"),
    }
    filtered = filter_fields_for_role("payroll.PayPayslip", {"resp_production"}, data)
    assert "net_to_pay" not in filtered
    assert "gross" not in filtered
    assert filtered["state"] == "approved"

    filtered_rh = filter_fields_for_role("payroll.PayPayslip", {"rh"}, data)
    assert filtered_rh["net_to_pay"] == Decimal("1000000")

    filtered_collaborateur = filter_fields_for_role("payroll.PayPayslip", {"collaborateur"}, data)
    assert filtered_collaborateur["net_to_pay"] == Decimal("1000000")
