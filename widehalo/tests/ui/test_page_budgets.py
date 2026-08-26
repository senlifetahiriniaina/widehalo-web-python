from __future__ import annotations

import gzip

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from django.test import Client

pytestmark = pytest.mark.django_db

MAX_HOME_PAGE_COMPRESSED_BYTES = 200 * 1024
MAX_HTMX_FRAGMENT_COMPRESSED_BYTES = 30 * 1024


def _logged_in_client() -> tuple[Client, Tenant]:
    tenant = Tenant.objects.create(code="UI-BUDGET", name="UI Budget Tenant")
    user = User.objects.create_user(email="ui-budget@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def test_dashboard_page_is_under_200kb_compressed() -> None:
    client, _tenant = _logged_in_client()
    response = client.get("/dashboard/")
    assert response.status_code == 200
    compressed = gzip.compress(response.content)
    assert len(compressed) < MAX_HOME_PAGE_COMPRESSED_BYTES


def test_smart_table_htmx_fragment_is_under_30kb_compressed() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(20):
            Partner.objects.create(tenant=tenant, name=f"Partner {i}", reference=f"PART-{i:04d}")

    response = client.get("/partners/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    compressed = gzip.compress(response.content)
    assert len(compressed) < MAX_HTMX_FRAGMENT_COMPRESSED_BYTES


def test_htmx_request_never_returns_a_full_html_document() -> None:
    """Une reponse a une requete HTMX ne doit jamais recharger la page
    complete : elle ne doit contenir ni <html> ni <head>, uniquement le
    fragment demande."""
    client, tenant = _logged_in_client()
    response = client.get("/partners/", HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert "<html" not in body.lower()
    assert "<head" not in body.lower()
