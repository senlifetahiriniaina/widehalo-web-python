"""Endpoint API de qualification (chantier RG-QUALIF) — `POST .../rows/
{id}/qualify` pour l'import de quantites initiales de stock."""

from __future__ import annotations

import io
import uuid

import openpyxl
import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.catalog.tests.factories import ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkImportRow
from apps.stocks.tests.factories import StkLocationFactory, StkWarehouseFactory

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
def tenant():
    return Tenant.objects.create(code="STK-QUALIF-API", name="Stocks Qualif API Tenant")


@pytest.fixture
def qualifier_user():
    user = User.objects.create_user(email="stk-qualif@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="stk-qualif-api-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="stocks",
            codename__in=[
                "add_stkimportbatch",
                "view_stkimportbatch",
                "change_stkimportrow",
                "view_stkimportrow",
                "qualify_stkimportrow",
            ],
        )
    )
    user.groups.add(group)
    return user


def test_qualify_stock_import_row_endpoint(tenant, qualifier_user) -> None:
    client = Client()
    token = _access_token(client, qualifier_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, reference="VAR-API-1")
        warehouse = StkWarehouseFactory(tenant=tenant, code="WH-API")
        location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC-API")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        ["Variant_code", "Warehouse_code", "Location_code", "Qty", "Unit_cost_mga", "Lot_reference"]
    )
    sheet.append([str(uuid.uuid4()), "WH-API", "INCONNU", 10, 100, ""])
    buffer = io.BytesIO()
    workbook.save(buffer)
    upload = io.BytesIO(buffer.getvalue())
    upload.name = "stock.xlsx"

    import_response = client.post(
        "/api/v1/stocks/imports/initial-quantities", {"file": upload}, **headers
    )
    row = import_response.json()["needs_qualification_rows"][0]
    assert row["uses_placeholder_variant"] is True
    assert row["uses_placeholder_location"] is True

    qualify_response = client.post(
        f"/api/v1/stocks/imports/initial-quantities/rows/{row['id']}/qualify",
        {"variant_id": str(variant.id), "location_id": str(location.id)},
        content_type="application/json",
        **headers,
    )

    assert qualify_response.status_code == 200
    data = qualify_response.json()
    assert data["uses_placeholder_variant"] is False
    assert data["uses_placeholder_location"] is False
    assert data["status"] in (
        StkImportRow.STATUS_QUALIFIED,
        StkImportRow.STATUS_PENDING_APPROVAL,
    )


def test_qualify_endpoint_forbidden_without_permission(tenant) -> None:
    unauthorized_user = User.objects.create_user(
        email="stk-no-perm@example.com", password="Str0ngPassw0rd!23"
    )
    client = Client()
    token = _access_token(client, unauthorized_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/stocks/imports/initial-quantities/rows/00000000-0000-7000-8000-000000000000/qualify",
        {},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 403
