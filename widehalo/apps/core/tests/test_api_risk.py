"""Tests API django-ninja du registre de risques (RSK1-2) : RBAC N2
(`require_permission`) et scoping "owner" pour les roles non
privilegies. `admin`/`direction` sont dans `CORE_MFA_REQUIRED_ROLES`
(cf. `apps.automation.tests.test_api`, meme contournement) : groupe ad
hoc portant les 3 permissions `core.*_riskitem` reellement exercees,
plutot que `grant_role("direction")`, pour eviter le blocage MFA au
login JWT."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role

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


def _full_visibility_user(email: str) -> User:
    """Utilisateur avec les 3 permissions `core.*_riskitem` (equivalent
    `admin`/`direction`) SANS passer par `grant_role` (MFA-gated, cf.
    docstring de module)."""
    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name=f"risk-full-{email}")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="core",
            codename__in=["view_riskitem", "add_riskitem", "change_riskitem"],
        )
    )
    user.groups.add(group)
    return user


def test_role_without_permission_is_denied() -> None:
    tenant = Tenant.objects.create(code="RSK-DENY", name="Risk API Deny Tenant")
    user = User.objects.create_user(email="rsk-deny@example.com", password="Str0ngPassw0rd!23")
    # "chef_atelier" n'a aucune entree dans CUSTOM_PERMISSIONS pour
    # `core.*_riskitem` et n'est pas dans CORE_MFA_REQUIRED_ROLES.
    grant_role(user, "chef_atelier")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    list_response = client.get("/api/v1/risks", **headers)
    assert list_response.status_code == 403

    create_response = client.post(
        "/api/v1/risks",
        {"category": "fournisseur", "likelihood": 3, "impact": 3},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 403


def test_add_view_role_can_create_and_see_only_own_risks() -> None:
    tenant = Tenant.objects.create(code="RSK-SCOPE", name="Risk API Scope Tenant")
    # "acheteur" : add+view (pas change) sur core.riskitem, non MFA-gated.
    owner = User.objects.create_user(email="rsk-owner@example.com", password="Str0ngPassw0rd!23")
    grant_role(owner, "acheteur")
    other = User.objects.create_user(email="rsk-other@example.com", password="Str0ngPassw0rd!23")
    grant_role(other, "acheteur")

    client = Client()
    owner_headers = _headers(
        _access_token(client, owner.email, "Str0ngPassw0rd!23"), str(tenant.id)
    )
    other_headers = _headers(
        _access_token(client, other.email, "Str0ngPassw0rd!23"), str(tenant.id)
    )

    create_response = client.post(
        "/api/v1/risks",
        {"category": "fournisseur", "likelihood": 3, "impact": 3},
        content_type="application/json",
        **owner_headers,
    )
    assert create_response.status_code == 200
    risk_id = create_response.json()["id"]

    owner_list = client.get("/api/v1/risks", **owner_headers).json()["results"]
    assert [r["id"] for r in owner_list] == [risk_id]

    other_list = client.get("/api/v1/risks", **other_headers).json()["results"]
    assert other_list == []

    # "acheteur" n'a pas `core.change_riskitem` : cloturer son propre
    # signalement via l'API generique reste refuse (limitation disclosed,
    # cf. commentaire de `rbac_policy.CUSTOM_PERMISSIONS`).
    close_response = client.post(f"/api/v1/risks/{risk_id}/close", **owner_headers)
    assert close_response.status_code == 403


def test_full_visibility_role_sees_every_risk_and_can_close() -> None:
    tenant = Tenant.objects.create(code="RSK-FULL", name="Risk API Full Tenant")
    reporter = User.objects.create_user(
        email="rsk-reporter@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(reporter, "acheteur")
    supervisor = _full_visibility_user("rsk-supervisor@example.com")

    client = Client()
    reporter_headers = _headers(
        _access_token(client, reporter.email, "Str0ngPassw0rd!23"), str(tenant.id)
    )
    supervisor_headers = _headers(
        _access_token(client, supervisor.email, "Str0ngPassw0rd!23"), str(tenant.id)
    )

    create_response = client.post(
        "/api/v1/risks",
        {"category": "production", "likelihood": 5, "impact": 5},
        content_type="application/json",
        **reporter_headers,
    )
    risk_id = create_response.json()["id"]
    assert create_response.json()["score"] == 25

    supervisor_list = client.get("/api/v1/risks", **supervisor_headers).json()["results"]
    assert risk_id in [r["id"] for r in supervisor_list]

    close_response = client.post(f"/api/v1/risks/{risk_id}/close", **supervisor_headers)
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "closed"
