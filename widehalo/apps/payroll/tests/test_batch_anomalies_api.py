"""Bloc E, E6 (PAY-7) : `GET /payroll/batches/{id}/anomalies` et
`POST /payroll/batches/{id}/anomalies/acknowledge` — et le cycle complet
via `POST /payroll/periods/{id}/validate`, qui reste sur le MEME lot
d'un appel a l'autre (`create_batch` idempotent)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.test import Client
from django_otp.oath import totp

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.payroll.models import PayBatch, PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def _mfa_access_token(client: Client, user: User, email: str) -> str:
    """`rh` appartient a `settings.CORE_MFA_REQUIRED_ROLES` — meme patron
    que `apps.payroll.tests.test_amend_contract_api._mfa_access_token`."""
    device = mfa_service.enroll_device(user)
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post(
        "/api/v1/auth/mfa/verify",
        {"email": email, "token": token},
        content_type="application/json",
    )
    access: str = response.json()["access"]
    return access


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def rh_setup():
    tenant = Tenant.objects.create(code="PAY-E6-API", name="E6 anomalies API")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        oecfm_user = User.objects.create_user(
            email="oecfm@example.com", password="Str0ngPassw0rd!23"
        )
        for parameter in RegulatoryParameter.objects.filter(tenant=tenant):
            parameter.mark_validated(oecfm_user)
        user = User.objects.create_user(email="rh@example.com", password="Str0ngPassw0rd!23")
        grant_role(user, "rh")
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
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
        payslip.save(update_fields=["state"])
        period.state = period.STATE_VERIFIED
        period.save(update_fields=["state"])
    client = Client()
    token = _mfa_access_token(client, user, "rh@example.com")
    return client, _headers(token, str(tenant.id)), tenant, period


def test_validate_period_returns_batch_id_even_on_anomaly_failure(rh_setup) -> None:
    client, headers, _tenant, period = rh_setup

    response = client.post(
        f"/api/v1/payroll/periods/{period.id}/validate",
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
    body = response.json()
    assert "batch_id" in body


def test_full_cycle_list_acknowledge_then_retry_validate_succeeds(rh_setup) -> None:
    client, headers, tenant, period = rh_setup

    first = client.post(
        f"/api/v1/payroll/periods/{period.id}/validate",
        content_type="application/json",
        **headers,
    )
    assert first.status_code == 400
    batch_id = first.json()["batch_id"]

    anomalies_response = client.get(f"/api/v1/payroll/batches/{batch_id}/anomalies", **headers)
    assert anomalies_response.status_code == 200
    anomalies = anomalies_response.json()
    assert anomalies
    assert all(not a["acknowledged"] for a in anomalies)

    for anomaly in anomalies:
        ack_response = client.post(
            f"/api/v1/payroll/batches/{batch_id}/anomalies/acknowledge",
            {"payslip_id": anomaly["payslip_id"], "code": anomaly["code"], "reason": "Examiné."},
            content_type="application/json",
            **headers,
        )
        assert ack_response.status_code == 200, ack_response.content

    second = client.post(
        f"/api/v1/payroll/periods/{period.id}/validate",
        content_type="application/json",
        **headers,
    )
    assert second.status_code == 200, second.content
    assert second.json()["batch_id"] == batch_id

    with use_tenant(tenant.id):
        batch = PayBatch.objects.get(id=batch_id)
        assert batch.state == PayBatch.STATE_VALIDATED
        assert PayBatch.objects.filter(tenant=tenant, period=period).count() == 1


def test_acknowledge_endpoint_requires_a_reason(rh_setup) -> None:
    client, headers, _tenant, period = rh_setup

    first = client.post(
        f"/api/v1/payroll/periods/{period.id}/validate",
        content_type="application/json",
        **headers,
    )
    batch_id = first.json()["batch_id"]
    anomalies = client.get(f"/api/v1/payroll/batches/{batch_id}/anomalies", **headers).json()

    response = client.post(
        f"/api/v1/payroll/batches/{batch_id}/anomalies/acknowledge",
        {"payslip_id": anomalies[0]["payslip_id"], "code": anomalies[0]["code"], "reason": ""},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
