"""Bloc E, E4 (PAY-5) : écran de simulation de rubrique sur salarié
témoin (`apps.payroll.views.rubric_simulation`) — appelle le même moteur
que `compute_payslip` contre un contrat réel, sans jamais persister."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPayslipLine
from apps.payroll.tests.factories import (
    employee_client,
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
    staff_client,
)

pytestmark = pytest.mark.django_db


def test_staff_role_can_simulate_and_sees_computed_lines() -> None:
    tenant = Tenant.objects.create(code="PAY-E4-V1", name="E4 view staff")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        client, _user = staff_client(tenant)

    response = client.get(
        "/payroll/simulation/", {"contract_id": str(contract.id), "period_id": str(period.id)}
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert "SAL_BASE" in content
    assert "1033300" in content  # NET_A_PAYER, meme hand-calc que l'acceptance n°1.


def test_simulation_never_persists_a_payslip_or_lines() -> None:
    tenant = Tenant.objects.create(code="PAY-E4-V2", name="E4 view no persist")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        client, _user = staff_client(tenant)

        payslips_before = PayPayslip.objects.count()
        lines_before = PayPayslipLine.objects.count()

        client.get(
            "/payroll/simulation/",
            {"contract_id": str(contract.id), "period_id": str(period.id)},
        )

        assert PayPayslip.objects.count() == payslips_before
        assert PayPayslipLine.objects.count() == lines_before


def test_non_staff_role_gets_403() -> None:
    tenant = Tenant.objects.create(code="PAY-E4-V3", name="E4 view non staff")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        client = employee_client(tenant, employee_id)

    response = client.get("/payroll/simulation/")
    assert response.status_code == 403


def test_screen_without_selection_shows_the_picker_only() -> None:
    tenant = Tenant.objects.create(code="PAY-E4-V4", name="E4 view picker")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        client, _user = staff_client(tenant)

    response = client.get("/payroll/simulation/")
    assert response.status_code == 200
    assert "Simulation sur salarié témoin" in response.content.decode()


def test_staff_view_logs_pii_access_on_simulation() -> None:
    tenant = Tenant.objects.create(code="PAY-E4-V5", name="E4 view PII log")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        contract = make_active_contract(
            tenant, employee_id=employee_id, wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        client, user = staff_client(tenant)

        assert not AuditLog.objects.filter(
            tenant_id=tenant.id, action=AuditLog.ACTION_PII_ACCESS
        ).exists()

        client.get(
            "/payroll/simulation/",
            {"contract_id": str(contract.id), "period_id": str(period.id)},
        )

        log = AuditLog.objects.get(tenant_id=tenant.id, action=AuditLog.ACTION_PII_ACCESS)
        assert log.actor_id == user.id
        assert str(log.object_id) == str(contract.id)
