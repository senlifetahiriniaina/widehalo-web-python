"""A12 — endpoints API pour ACC-IS/ACC-IR/ACC-EXPORT-FISC1."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

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


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


def _ledger(fiscal_regime: str):
    tenant = Tenant.objects.create(
        code="ACC-A12-API", name="A12 API Tenant", fiscal_regime=fiscal_regime
    )
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant, code="OD", name="OD", type=AccJournal.TYPE_MISC, sequence_prefix="OD"
        )
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )

        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 10)
        )
        add_line(move, account=receivable, label="Vente", debit=Decimal("5000"))
        add_line(move, account=income, label="Vente", credit=Decimal("5000"))
        post_move(move)

    return {"tenant": tenant, "fiscal_year": fiscal_year}


@pytest.fixture
def synthetic_ledger():
    return _ledger(Tenant.FISCAL_REGIME_SYNTHETIC)


@pytest.fixture
def real_ledger():
    return _ledger(Tenant.FISCAL_REGIME_REAL_WITH_VAT)


@pytest.fixture
def a12_user():
    user = User.objects.create_user(email="a12-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="accounting-a12-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=["view_accaccount", "view_accasset"],
        )
    )
    user.groups.add(group)
    return user


def test_liasse_is_endpoint_returns_a_pdf_for_a_synthetic_tenant(
    synthetic_ledger, a12_user
) -> None:
    tenant = synthetic_ledger["tenant"]
    fiscal_year = synthetic_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a12_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        f"/api/v1/accounting/reports/liasse-is?fiscal_year_id={fiscal_year.id}", **headers
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_liasse_is_endpoint_rejects_a_real_regime_tenant(real_ledger, a12_user) -> None:
    tenant = real_ledger["tenant"]
    fiscal_year = real_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a12_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        f"/api/v1/accounting/reports/liasse-is?fiscal_year_id={fiscal_year.id}", **headers
    )
    assert response.status_code == 400


def test_liasse_ir_endpoint_returns_a_pdf_for_a_real_regime_tenant(real_ledger, a12_user) -> None:
    tenant = real_ledger["tenant"]
    fiscal_year = real_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a12_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        f"/api/v1/accounting/reports/liasse-ir?fiscal_year_id={fiscal_year.id}", **headers
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_liasse_ir_endpoint_rejects_a_synthetic_regime_tenant(synthetic_ledger, a12_user) -> None:
    tenant = synthetic_ledger["tenant"]
    fiscal_year = synthetic_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a12_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        f"/api/v1/accounting/reports/liasse-ir?fiscal_year_id={fiscal_year.id}", **headers
    )
    assert response.status_code == 400


def test_export_canevas_notes_endpoint(real_ledger, a12_user) -> None:
    tenant = real_ledger["tenant"]
    client = Client()
    token = _access_token(client, a12_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/accounting/reports/export-canevas-notes", **headers)
    assert response.status_code == 200
    results = response.json()["results"]
    for code in ("ACC-TVA", "ACC-DCOM", "ACC-IRSA", "ACC-IS", "ACC-IR"):
        assert code in results


def test_fixed_asset_annexes_endpoint_supports_csv_export(real_ledger, a12_user) -> None:
    tenant = real_ledger["tenant"]
    fiscal_year = real_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a12_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        "/api/v1/accounting/reports/fixed-asset-annexes"
        f"?fiscal_year_id={fiscal_year.id}&format=csv",
        **headers,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "annexe" in response.content.decode("utf-8").splitlines()[0]
