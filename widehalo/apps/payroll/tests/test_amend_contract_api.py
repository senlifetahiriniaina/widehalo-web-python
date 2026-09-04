"""Bloc E, E5 (PAY-6) : `POST /api/v1/payroll/contracts/{id}/amend` —
point d'entrée réel de `create_amendment`, jamais appelé en pratique
avant ce sprint (audit PAY-6). Même patron d'authentification que
`apps/payroll/tests/test_api.py` (JWT, `grant_role`)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.payroll.models import PayContract
from apps.payroll.tests.factories import make_active_contract, setup_payroll_reference_data

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _mfa_access_token(client: Client, user: User, email: str) -> str:
    """`rh` appartient a `settings.CORE_MFA_REQUIRED_ROLES` — `/api/v1/auth/
    login` renvoie `access: None` (`status: mfa_enrollment_required`/
    `mfa_required`) tant que la session n'a pas complete l'enrolement +
    verification TOTP via `/api/v1/auth/mfa/verify` (flux API, distinct du
    flux web `/mfa/`), meme patron que
    `apps.core.tests.test_mfa_enforcement.
    test_mfa_verify_with_correct_totp_completes_login`."""
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
def rh_client():
    tenant = Tenant.objects.create(code="PAY-E5-API", name="E5 amend API Tenant")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        user = User.objects.create_user(email="rh@example.com", password="Str0ngPassw0rd!23")
        grant_role(user, "rh")
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
    client = Client()
    token = _mfa_access_token(client, user, "rh@example.com")
    return client, _headers(token, str(tenant.id)), tenant, contract


def test_amend_endpoint_creates_a_child_contract(rh_client) -> None:
    client, headers, tenant, contract = rh_client

    response = client.post(
        f"/api/v1/payroll/contracts/{contract.id}/amend",
        {"date_start": "2026-06-01", "wage_base": "1500000"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["id"] != str(contract.id)

    with use_tenant(tenant.id):
        amendment = PayContract.objects.get(id=body["id"])
        assert amendment.parent_contract_id == contract.id
        assert amendment.wage_base == Decimal("1500000")


def test_amend_endpoint_requires_add_paycontract_permission() -> None:
    tenant = Tenant.objects.create(code="PAY-E5-API2", name="E5 amend API no perm")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        User.objects.create_user(email="nogrant@example.com", password="Str0ngPassw0rd!23")
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
    client = Client()
    token = _access_token(client, "nogrant@example.com", "Str0ngPassw0rd!23")

    response = client.post(
        f"/api/v1/payroll/contracts/{contract.id}/amend",
        {"date_start": "2026-06-01"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )

    assert response.status_code == 403


def test_amend_endpoint_returns_404_for_unknown_contract(rh_client) -> None:
    client, headers, _tenant, _contract = rh_client

    response = client.post(
        f"/api/v1/payroll/contracts/{uuid.uuid4()}/amend",
        {"date_start": "2026-06-01"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 404
