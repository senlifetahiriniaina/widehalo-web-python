"""PRC1-3 : API django-ninja de la veille prix fournisseurs — CRUD cibles,
listing des releves, declenchement manuel, et RBAC (`acheteur` autorise,
un role hors perimetre `purchase`/`purchase.run_price_watch_check`
refuse)."""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.purchase.models import PrcPriceWatchTarget
from apps.purchase.tests.factories import PrcPriceWatchTargetFactory

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
def api_price_watch():
    tenant = Tenant.objects.create(code="PRC-API", name="Price Watch API Tenant")
    user = User.objects.create_user(email="prc-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "acheteur")
    return tenant, user


def test_create_and_list_price_watch_target_via_api(api_price_watch) -> None:
    tenant, user = api_price_watch
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/purchase/price-watch/targets",
        {
            "platform_code": PrcPriceWatchTarget.PLATFORM_ALIBABA,
            "search_query_or_url": "https://alibaba.com/search?q=tissu",
            "currency": "USD",
            "frequency": PrcPriceWatchTarget.FREQUENCY_MONTHLY,
            "variant_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["platform_code"] == PrcPriceWatchTarget.PLATFORM_ALIBABA
    assert body["variant_id"] is not None

    list_response = client.get("/api/v1/purchase/price-watch/targets", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1


def test_create_price_watch_target_rejects_both_references_via_api(api_price_watch) -> None:
    tenant, user = api_price_watch
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/purchase/price-watch/targets",
        {
            "platform_code": PrcPriceWatchTarget.PLATFORM_ALIBABA,
            "search_query_or_url": "tissu",
            "material_reference_id": str(uuid.uuid4()),
            "variant_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 422


def test_manual_check_and_list_snapshots_via_api(api_price_watch) -> None:
    tenant, user = api_price_watch
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)

    check_response = client.post(
        f"/api/v1/purchase/price-watch/targets/{target.id}/check", **headers
    )
    assert check_response.status_code == 200
    body = check_response.json()
    assert body["is_stub"] is True
    assert body["observed_price"] is None

    snapshots_response = client.get(
        f"/api/v1/purchase/price-watch/targets/{target.id}/snapshots", **headers
    )
    assert snapshots_response.status_code == 200
    assert len(snapshots_response.json()["results"]) == 1


def test_price_watch_endpoints_denied_for_role_without_purchase_access() -> None:
    """`collaborateur` (role sans MFA, cf. `settings.CORE_MFA_REQUIRED_ROLES`,
    ne pas confondre avec `rh`/`comptable` qui l'exigent et compliqueraient
    inutilement ce test d'authentification simple) n'a aucun acces
    `purchase` dans `ROLE_APP_PERMISSIONS`."""
    tenant = Tenant.objects.create(code="PRC-API-RBAC", name="Price Watch RBAC Tenant")
    user = User.objects.create_user(email="prc-rbac@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "collaborateur")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/purchase/price-watch/targets", **headers)
    assert response.status_code == 403


def test_manual_check_denied_without_run_price_watch_check_permission() -> None:
    """`purchase.run_price_watch_check` (cf. rbac_policy) n'est accorde qu'a
    `admin`/`direction`/`acheteur` — `collaborateur` (aucun acces `purchase`)
    se voit refuser le declenchement manuel."""
    tenant = Tenant.objects.create(code="PRC-API-RBAC2", name="Price Watch RBAC Tenant 2")
    user = User.objects.create_user(email="prc-rbac2@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "collaborateur")
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(f"/api/v1/purchase/price-watch/targets/{target.id}/check", **headers)
    assert response.status_code == 403
