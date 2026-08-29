"""PRC1-3 : ecrans HTMX de la veille prix fournisseurs (liste + creation +
verification manuelle inline, historique des releves)."""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.purchase.models import PrcPriceSnapshot, PrcPriceWatchTarget
from apps.purchase.tests.factories import PrcPriceWatchTargetFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_price_watch():
    tenant = Tenant.objects.create(code="PRC-WEB", name="Price Watch Web Tenant")
    user = User.objects.create_user(email="prc-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "acheteur")
    return tenant, user


def _authenticated_client(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_price_watch_list_screen_renders(web_price_watch) -> None:
    tenant, user = web_price_watch
    client = _authenticated_client(tenant, user)

    response = client.get("/purchase/price-watch/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_price_watch_list_screen_creates_target(web_price_watch) -> None:
    tenant, user = web_price_watch
    client = _authenticated_client(tenant, user)

    response = client.post(
        "/purchase/price-watch/",
        {
            "action": "create",
            "platform_code": PrcPriceWatchTarget.PLATFORM_ALIBABA,
            "search_query_or_url": "tissu coton 200g",
            "currency": "USD",
            "frequency": PrcPriceWatchTarget.FREQUENCY_MONTHLY,
            "variant_id": str(uuid.uuid4()),
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert PrcPriceWatchTarget.objects.filter(tenant=tenant).count() == 1


def test_price_watch_list_screen_rejects_both_references(web_price_watch) -> None:
    tenant, user = web_price_watch
    client = _authenticated_client(tenant, user)

    response = client.post(
        "/purchase/price-watch/",
        {
            "action": "create",
            "platform_code": PrcPriceWatchTarget.PLATFORM_ALIBABA,
            "search_query_or_url": "tissu coton",
            "material_reference_id": str(uuid.uuid4()),
            "variant_id": str(uuid.uuid4()),
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200  # re-rendu avec erreur, pas de redirection
    with use_tenant(tenant.id):
        assert PrcPriceWatchTarget.objects.filter(tenant=tenant).count() == 0


def test_price_watch_list_screen_manual_check_creates_stub_snapshot(web_price_watch) -> None:
    tenant, user = web_price_watch
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)
    client = _authenticated_client(tenant, user)

    response = client.post(
        "/purchase/price-watch/",
        {"action": "check", "target_id": str(target.id)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        snapshot = PrcPriceSnapshot.objects.get(target=target)
        assert snapshot.is_stub is True


def test_price_watch_history_screen_renders(web_price_watch) -> None:
    tenant, user = web_price_watch
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)
    client = _authenticated_client(tenant, user)

    response = client.get(
        f"/purchase/price-watch/{target.id}/history/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert response.status_code == 200
