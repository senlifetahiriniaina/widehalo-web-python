"""Tests des ecrans HTMX du registre de risques (RSK1-2) : liste (SmartTable)
et detail — meme idiome que `apps.partners.tests` (client Django, session
tenant, `force_login`)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.factories import RiskItemFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _client_for(user: User, tenant: Tenant) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_risk_list_screen_renders_for_authenticated_user() -> None:
    tenant = Tenant.objects.create(code="RSK-SCR-LIST", name="Risk Screen List Tenant")
    user = User.objects.create_user(
        email="rsk-screen-list@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        RiskItemFactory(tenant=tenant, owner=user)

    client = _client_for(user, tenant)
    response = client.get("/risks/")

    assert response.status_code == 200
    assert b"Registre des risques" in response.content


def test_risk_detail_screen_shows_score_and_owner() -> None:
    tenant = Tenant.objects.create(code="RSK-SCR-DETAIL", name="Risk Screen Detail Tenant")
    user = User.objects.create_user(
        email="rsk-screen-detail@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        risk_item = RiskItemFactory(tenant=tenant, owner=user, likelihood=4, impact=3, score=12)

    client = _client_for(user, tenant)
    response = client.get(f"/risks/{risk_item.id}/")

    assert response.status_code == 200
    assert b"12" in response.content


def test_risk_detail_denies_access_to_non_owner_without_full_visibility() -> None:
    tenant = Tenant.objects.create(code="RSK-SCR-DENY", name="Risk Screen Deny Tenant")
    owner = User.objects.create_user(
        email="rsk-screen-owner@example.com", password="Str0ngPassw0rd!23"
    )
    stranger = User.objects.create_user(
        email="rsk-screen-stranger@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        risk_item = RiskItemFactory(tenant=tenant, owner=owner)

    client = _client_for(stranger, tenant)
    response = client.get(f"/risks/{risk_item.id}/")

    assert response.status_code == 404


def test_risk_create_screen_renders_form() -> None:
    tenant = Tenant.objects.create(code="RSK-SCR-CREATE", name="Risk Screen Create Tenant")
    user = User.objects.create_user(
        email="rsk-screen-create@example.com", password="Str0ngPassw0rd!23"
    )
    client = _client_for(user, tenant)

    response = client.get("/risks/new/")

    assert response.status_code == 200
    assert b"Signaler un risque" in response.content
