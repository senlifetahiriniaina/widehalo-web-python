"""Tests API django-ninja des gabarits de controle qualite / inspections
(QLT1-2) : RBAC N2 (`require_permission`), pas de scoping "owner" (cf.
docstring de `apps.core.api_quality`) — meme idiome que
`apps.core.tests.test_api_risk` pour le contournement MFA
(`_full_visibility_user`)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role

pytestmark = pytest.mark.django_db

_QLT_CODENAMES = [
    "view_qltchecklisttemplate",
    "add_qltchecklisttemplate",
    "change_qltchecklisttemplate",
    "view_qltinspection",
    "add_qltinspection",
    "change_qltinspection",
]


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def _full_visibility_user(email: str) -> User:
    """Utilisateur avec les 6 permissions `core.*_qlt*` (equivalent
    `admin`/`direction`) SANS passer par `grant_role` (MFA-gated) — meme
    contournement que `apps.core.tests.test_api_risk._full_visibility_user`."""
    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name=f"qlt-full-{email}")
    group.permissions.set(
        Permission.objects.filter(content_type__app_label="core", codename__in=_QLT_CODENAMES)
    )
    user.groups.add(group)
    return user


def test_role_without_permission_is_denied() -> None:
    tenant = Tenant.objects.create(code="QLT-DENY", name="Quality API Deny Tenant")
    user = User.objects.create_user(email="qlt-deny@example.com", password="Str0ngPassw0rd!23")
    # "magasinier" n'a aucune entree dans CUSTOM_PERMISSIONS pour
    # `core.*_qlt*` et n'est pas dans CORE_MFA_REQUIRED_ROLES.
    grant_role(user, "magasinier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    list_response = client.get("/api/v1/quality/templates", **headers)
    assert list_response.status_code == 403

    create_response = client.post(
        "/api/v1/quality/templates",
        {"name": "Controle", "items": []},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 403


def test_domain_role_can_create_template_and_inspection() -> None:
    tenant = Tenant.objects.create(code="QLT-DOMAIN", name="Quality API Domain Tenant")
    user = User.objects.create_user(email="qlt-domain@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_production")

    client = Client()
    headers = _headers(_access_token(client, user.email, "Str0ngPassw0rd!23"), str(tenant.id))

    create_template = client.post(
        "/api/v1/quality/templates",
        {
            "name": "Controle couture",
            "items": [{"code": "C1", "label": "Solidite", "expected": "OK"}],
        },
        content_type="application/json",
        **headers,
    )
    assert create_template.status_code == 200
    template_id = create_template.json()["id"]

    templates = client.get("/api/v1/quality/templates", **headers).json()["results"]
    assert template_id in [t["id"] for t in templates]

    create_inspection = client.post(
        "/api/v1/quality/inspections",
        {
            "template_id": template_id,
            "results": [{"code": "C1", "status": "conforme", "comment": ""}],
            "inspected_at": "2026-08-29T10:00:00Z",
        },
        content_type="application/json",
        **headers,
    )
    assert create_inspection.status_code == 200
    body = create_inspection.json()
    assert body["passed"] is True

    inspections = client.get("/api/v1/quality/inspections", **headers).json()["results"]
    assert body["id"] in [i["id"] for i in inspections]


def test_failed_inspection_is_reported_as_not_passed() -> None:
    tenant = Tenant.objects.create(code="QLT-FAIL", name="Quality API Fail Tenant")
    user = _full_visibility_user("qlt-fail@example.com")

    client = Client()
    headers = _headers(_access_token(client, user.email, "Str0ngPassw0rd!23"), str(tenant.id))

    template_id = client.post(
        "/api/v1/quality/templates",
        {"name": "Controle", "items": []},
        content_type="application/json",
        **headers,
    ).json()["id"]

    inspection = client.post(
        "/api/v1/quality/inspections",
        {
            "template_id": template_id,
            "results": [{"code": "C1", "status": "non_conforme", "comment": "Defaut"}],
            "inspected_at": "2026-08-29T10:00:00Z",
        },
        content_type="application/json",
        **headers,
    )
    assert inspection.status_code == 200
    assert inspection.json()["passed"] is False
