"""API django-ninja du module `presence` — meme patron que
`apps.logistics.tests.test_api` (JWT reel via `django.test.Client`).

Test d'acceptance §5.9.8 n°4 : un employe ne peut pas consulter le
pointage d'un collegue (`test_collaborateur_only_sees_own_attendance`)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant
from apps.presence.services.attendance import check_in
from apps.presence.services.employees import create_employee

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _access_token_mfa(client: Client, user: User, password: str) -> str:
    """ "rh" fait partie de `settings.CORE_MFA_REQUIRED_ROLES` (Lot 1,
    etape 4) — un simple `POST /auth/login` ne suffit pas, il faut
    enroler+confirmer un device TOTP puis passer par `/auth/mfa/verify`
    (meme flux que `apps.core.tests.test_mfa_enforcement`)."""
    from django_otp.oath import totp

    device = mfa_service.enroll_device(user)
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post(
        "/api/v1/auth/mfa/verify",
        {"email": user.email, "token": token},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_presence():
    tenant = Tenant.objects.create(code="PRS-API", name="Presence API Tenant")
    rh_user = User.objects.create_user(email="rh-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(rh_user, "rh")
    return tenant, rh_user


def test_create_employee_and_check_in_via_api(api_presence) -> None:
    tenant, rh_user = api_presence
    client = Client()
    token = _access_token_mfa(client, rh_user, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/presence/employees",
        {"first_name": "Rina", "last_name": "Rakoto", "hire_date": "2026-01-05"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    employee_id = create_response.json()["id"]

    checkin_response = client.post(
        "/api/v1/presence/check-in",
        {"employee_id": employee_id, "mode": "web"},
        content_type="application/json",
        **headers,
    )
    assert checkin_response.status_code == 200
    attendance_id = checkin_response.json()["id"]

    checkout_response = client.post(
        "/api/v1/presence/check-out",
        {"attendance_id": attendance_id},
        content_type="application/json",
        **headers,
    )
    assert checkout_response.status_code == 200

    list_response = client.get("/api/v1/presence/attendances", **headers)
    assert list_response.status_code == 200
    assert any(a["id"] == attendance_id for a in list_response.json()["results"])


def test_endpoint_without_permission_returns_403(api_presence) -> None:
    tenant, _rh_user = api_presence
    client = Client()
    other = User.objects.create_user(email="norole@example.com", password="Str0ngPassw0rd!23")
    token = _access_token(client, other.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/presence/employees", **headers)
    assert response.status_code == 403


def test_collaborateur_only_sees_own_attendance(api_presence) -> None:
    """Test d'acceptance §5.9.8 n°4."""
    tenant, _rh_user = api_presence
    with use_tenant(tenant.id):
        user_a = User.objects.create_user(
            email="employee-a@example.com", password="Str0ngPassw0rd!23"
        )
        user_b = User.objects.create_user(
            email="employee-b@example.com", password="Str0ngPassw0rd!23"
        )
        grant_role(user_a, "collaborateur")
        grant_role(user_b, "collaborateur")
        employee_a = create_employee(
            tenant, first_name="A", last_name="Employee", hire_date=dt.date(2026, 1, 1), user=user_a
        )
        employee_b = create_employee(
            tenant, first_name="B", last_name="Employee", hire_date=dt.date(2026, 1, 1), user=user_b
        )
        check_in(employee_a, mode="web", at=timezone.now())
        check_in(employee_b, mode="web", at=timezone.now())

    client = Client()
    token = _access_token(client, user_a.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/presence/attendances", **headers)
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["employee_id"] == str(employee_a.id)
