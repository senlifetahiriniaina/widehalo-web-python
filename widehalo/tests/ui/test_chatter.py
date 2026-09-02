"""Chatter generique (Sprint 3 / L2 de la refonte UX, cf.
docs/planning/2026-refonte-ux-sprints.md §5) : `apps.core.views.chatter` +
`apps.core.services.chatter`, premiere utilisation reelle sur
`/sales/orders/<id>/`. Meme idiome de connexion que
`tests/ui/test_smart_table_bulk_and_saved_views.py`."""

from __future__ import annotations

import pytest
from apps.core.models.chatter import ChatterMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.chatter import post_message, thread_for
from apps.core.tests.utils import use_tenant
from apps.sales.tests.factories import SalesOrderFactory
from django.test import Client

pytestmark = pytest.mark.django_db


def _logged_in_client() -> tuple[Client, Tenant, User]:
    tenant = Tenant.objects.create(code="UI-CHATTER", name="UI Chatter Tenant")
    user = User.objects.create_user(email="ui-chatter@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user


def test_post_message_service_creates_message_on_thread() -> None:
    tenant = Tenant.objects.create(code="SVC-CHATTER", name="Service Chatter Tenant")
    user = User.objects.create_user(email="svc-chatter@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)
        post_message(order, author=user, body="Bonjour")
        post_message(order, author=user, body="Confidentiel", is_note=True)

        thread = list(thread_for(order))
        assert [m.body for m in thread] == ["Bonjour", "Confidentiel"]
        assert thread[1].is_note is True
        assert thread[0].tenant_id == tenant.id


def test_order_detail_lazy_loads_chatter_via_htmx() -> None:
    client, tenant, _user = _logged_in_client()
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)

    body = client.get(f"/sales/orders/{order.id}/").content.decode()
    assert f"/chatter/sales/salesorder/{order.id}/" in body


def test_chatter_thread_get_returns_fragment() -> None:
    client, tenant, user = _logged_in_client()
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)
        post_message(order, author=user, body="Premier message")

    response = client.get(f"/chatter/sales/salesorder/{order.id}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Premier message" in body
    assert "<html" not in body.lower()


def test_chatter_thread_post_creates_message_and_refreshes_fragment() -> None:
    client, tenant, _user = _logged_in_client()
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)

    response = client.post(
        f"/chatter/sales/salesorder/{order.id}/",
        {"body": "Un nouveau message"},
    )
    assert response.status_code == 200
    assert "Un nouveau message" in response.content.decode()

    with use_tenant(tenant.id):
        assert ChatterMessage.objects.filter(object_id=str(order.id)).count() == 1


def test_chatter_thread_post_internal_note_is_flagged() -> None:
    client, tenant, _user = _logged_in_client()
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)

    client.post(
        f"/chatter/sales/salesorder/{order.id}/",
        {"body": "Note privée", "is_note": "on"},
    )

    with use_tenant(tenant.id):
        message = ChatterMessage.objects.get(object_id=str(order.id))
        assert message.is_note is True


def test_chatter_thread_returns_404_for_unknown_object() -> None:
    client, _tenant, _user = _logged_in_client()
    response = client.get("/chatter/sales/salesorder/00000000-0000-0000-0000-000000000000/")
    assert response.status_code == 404
