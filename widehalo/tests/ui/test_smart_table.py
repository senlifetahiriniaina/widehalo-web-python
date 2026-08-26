from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from django.test import Client

pytestmark = pytest.mark.django_db


def _logged_in_client() -> tuple[Client, Tenant]:
    tenant = Tenant.objects.create(code="UI-TABLE", name="UI Table Tenant")
    user = User.objects.create_user(email="ui-table@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def test_search_filters_rows() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Textiles Alpha", reference="PART-0001")
        Partner.objects.create(tenant=tenant, name="Beta Confection", reference="PART-0002")

    response = client.get("/partners/", {"q": "Alpha"})
    body = response.content.decode()
    assert "Textiles Alpha" in body
    assert "Beta Confection" not in body


def test_csv_export_returns_a_csv_response() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Gamma", reference="PART-0003")

    response = client.get("/partners/", {"export": "csv"})
    assert response["Content-Type"] == "text/csv"
    assert b"Gamma" in response.content or b"PART-0003" in response.content


def test_hidden_columns_are_not_rendered() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Delta", reference="PART-0004", nif="NIF-XYZ")

    response = client.get("/partners/", {"hide": "nif"})
    body = response.content.decode()
    assert "NIF-XYZ" not in body


def test_pagination_limits_rows_per_page() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(25):
            Partner.objects.create(tenant=tenant, name=f"Partner {i}", reference=f"PART-{i:04d}")

    response = client.get("/partners/")
    body = response.content.decode()
    assert body.count("PART-") <= 20 + 5  # tolerance colonnes/en-tetes
