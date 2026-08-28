"""Test d'acceptance §5.10.10 n°5 : un employe ne peut pas acceder au
bulletin d'un collegue (403 API)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.services.employees import create_employee

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def payroll_two_employees():
    tenant = Tenant.objects.create(code="PAY-API", name="Payroll API Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        user_a = User.objects.create_user(email="pay-a@example.com", password="Str0ngPassw0rd!23")
        user_b = User.objects.create_user(email="pay-b@example.com", password="Str0ngPassw0rd!23")
        grant_role(user_a, "collaborateur")
        grant_role(user_b, "collaborateur")
        create_employee(
            tenant, first_name="A", last_name="Employee", hire_date=dt.date(2024, 1, 1), user=user_a
        )
        employee_b = create_employee(
            tenant, first_name="B", last_name="Employee", hire_date=dt.date(2024, 1, 1), user=user_b
        )
        contract_b = make_active_contract(
            tenant, employee_id=employee_b.id, wage_base=Decimal("800000")
        )
        period = make_period(tenant)
        payslip_b = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=employee_b.id,
            contract=contract_b,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(payslip_b)
    return tenant, user_a, user_b, payslip_b


def test_collaborateur_cannot_access_colleague_payslip_pdf(payroll_two_employees) -> None:
    """Test d'acceptance §5.10.10 n°5."""
    tenant, user_a, _user_b, payslip_b = payroll_two_employees
    client = Client()
    token = _access_token(client, user_a.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(f"/api/v1/payroll/payslips/{payslip_b.id}/pdf", **headers)
    assert response.status_code == 403


def test_collaborateur_list_only_returns_own_payslip(payroll_two_employees) -> None:
    tenant, _user_a, user_b, payslip_b = payroll_two_employees
    client = Client()
    token = _access_token(client, user_b.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/payroll/payslips", **headers)
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["id"] == str(payslip_b.id)
    # RG-PAY-9 : l'employe voit SES PROPRES montants (pas masques).
    assert "net_to_pay" in results[0]
