"""Tests API django-ninja de `apps.core.api_backup` (BKP4) : garde
`is_superuser` STRICT (`require_superuser`), jamais une permission
RBAC/role `admin`/`direction` (correction actee apres le demarrage du
chantier, cf. `apps.core.api_backup` et rapport de fin de chantier) —
confirmation stricte revalidee cote serveur pour restauration/
reinitialisation."""

from __future__ import annotations

import pytest
from django.test import Client
from django_otp.oath import totp

from apps.core.models.backup import TenantDataOperation
from apps.core.models.risk import CATEGORY_OTHER, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


def _mfa_access_token(client: Client, user: User) -> str:
    """`admin`/`direction` (`CORE_MFA_REQUIRED_ROLES`) ET tout
    `is_superuser` (cf. `apps.core.services.mfa.mfa_required_for_user` :
    `... or user.is_superuser`) declenchent le gating MFA obligatoire —
    enrole et confirme un device TOTP AVANT le login API (memes primitives
    que `apps.core.tests.test_account_menu._logged_in_admin_client`,
    adaptees a l'API `/api/v1/auth/mfa/confirm` plutot qu'a l'ecran web
    `/mfa/`)."""
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post(
        "/api/v1/auth/mfa/confirm",
        {"email": user.email, "token": token},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def _superuser(email: str) -> User:
    return User.objects.create_superuser(email=email, password="Str0ngPassw0rd!23")


def test_admin_role_non_superuser_is_denied() -> None:
    """`admin`/`direction` NON superuser doivent recevoir 403 — le point
    precis de la correction actee : ce n'est PAS une permission RBAC."""
    tenant = Tenant.objects.create(code="BKAPI-DENY", name="Backup API Deny")
    user = User.objects.create_user(email="bkapi-deny@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "admin")
    client = Client()
    headers = _headers(_mfa_access_token(client, user), str(tenant.id))

    assert client.get("/api/v1/core/backups", **headers).status_code == 403
    assert client.post("/api/v1/core/backups", **headers).status_code == 403
    assert (
        client.post(
            "/api/v1/core/reset",
            {"confirm": tenant.code},
            content_type="application/json",
            **headers,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/core/backup-schedule", **headers).status_code == 403


def test_superuser_can_create_and_list_backups() -> None:
    tenant = Tenant.objects.create(code="BKAPI-DOMAIN", name="Backup API Domain")
    user = _superuser("bkapi-domain@example.com")
    client = Client()
    headers = _headers(_mfa_access_token(client, user), str(tenant.id))

    with use_tenant(tenant.id):
        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=1, impact=1, score=1, owner=user
        )

    create_response = client.post("/api/v1/core/backups", **headers)
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["status"] == TenantDataOperation.STATUS_SUCCESS
    assert body["document_id"] is not None

    list_response = client.get("/api/v1/core/backups", **headers)
    assert list_response.status_code == 200
    assert body["id"] in [o["id"] for o in list_response.json()["results"]]


def test_reset_requires_exact_tenant_code_confirmation() -> None:
    tenant = Tenant.objects.create(code="BKAPI-RESET", name="Backup API Reset")
    user = _superuser("bkapi-reset@example.com")
    client = Client()
    headers = _headers(_mfa_access_token(client, user), str(tenant.id))

    wrong_confirm = client.post(
        "/api/v1/core/reset",
        {"confirm": "wrong-code"},
        content_type="application/json",
        **headers,
    )
    assert wrong_confirm.status_code == 400
    assert (
        TenantDataOperation.all_objects.filter(
            tenant=tenant, operation_type=TenantDataOperation.TYPE_RESET
        ).count()
        == 0
    )

    right_confirm = client.post(
        "/api/v1/core/reset",
        {"confirm": tenant.code},
        content_type="application/json",
        **headers,
    )
    assert right_confirm.status_code == 200
    assert right_confirm.json()["status"] == TenantDataOperation.STATUS_SUCCESS


def test_restore_requires_exact_tenant_code_confirmation() -> None:
    tenant = Tenant.objects.create(
        code="BKAPI-RESTORE", name="Backup API Restore", country_code="MG"
    )
    user = _superuser("bkapi-restore@example.com")
    client = Client()
    headers = _headers(_mfa_access_token(client, user), str(tenant.id))

    with use_tenant(tenant.id):
        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=1, impact=1, score=1, owner=user
        )
    backup_id = client.post("/api/v1/core/backups", **headers).json()["document_id"]

    wrong_confirm = client.post(
        "/api/v1/core/backups/restore",
        {"confirm": "wrong-code", "document_id": backup_id},
        **headers,
    )
    assert wrong_confirm.status_code == 400

    right_confirm = client.post(
        "/api/v1/core/backups/restore",
        {"confirm": tenant.code, "document_id": backup_id},
        **headers,
    )
    assert right_confirm.status_code == 200
    assert right_confirm.json()["status"] == TenantDataOperation.STATUS_SUCCESS


def test_backup_schedule_get_or_create_and_update() -> None:
    tenant = Tenant.objects.create(code="BKAPI-SCHED", name="Backup API Schedule")
    user = _superuser("bkapi-sched@example.com")
    client = Client()
    headers = _headers(_mfa_access_token(client, user), str(tenant.id))

    get_response = client.get("/api/v1/core/backup-schedule", **headers)
    assert get_response.status_code == 200
    assert get_response.json()["frequency"] == "daily"

    update_response = client.put(
        "/api/v1/core/backup-schedule",
        {"frequency": "weekly", "retention_count": 3, "is_active": False},
        content_type="application/json",
        **headers,
    )
    assert update_response.status_code == 200
    body = update_response.json()
    assert body["frequency"] == "weekly"
    assert body["retention_count"] == 3
    assert body["is_active"] is False
