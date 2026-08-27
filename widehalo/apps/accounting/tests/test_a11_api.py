"""A11 — endpoints API pour ACC-DCOM1/ACC-IRCM/ACC-FONCIER."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccLocalTax, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

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


@pytest.fixture
def a11_ledger():
    tenant = Tenant.objects.create(
        code="ACC-A11-API", name="A11 API Tenant", fiscal_regime=Tenant.FISCAL_REGIME_REAL_WITH_VAT
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
        purchase_account = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        supplier_account = _make_account(
            tenant, code="401", name="Fournisseurs", account_class=4, type=AccAccount.TYPE_PAYABLE
        )
        financial_income_account = _make_account(
            tenant,
            code="762",
            name="Revenus des creances",
            account_class=7,
            type=AccAccount.TYPE_INCOME,
        )
        bank_account = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        partner_id = uuid.uuid4()

        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 10)
        )
        add_line(move, account=purchase_account, label="Achat", debit=Decimal("500000"))
        add_line(
            move,
            account=supplier_account,
            label="Achat",
            credit=Decimal("500000"),
            partner_id=partner_id,
        )
        post_move(move)

        ircm_move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 12)
        )
        add_line(ircm_move, account=bank_account, label="Interets", debit=Decimal("100000"))
        add_line(
            ircm_move,
            account=financial_income_account,
            label="Interets",
            credit=Decimal("100000"),
        )
        post_move(ircm_move)

    return {"tenant": tenant, "fiscal_year": fiscal_year}


@pytest.fixture
def a11_user():
    user = User.objects.create_user(email="a11-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="accounting-a11-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=[
                "add_accdcomdeclaration",
                "view_accdcomdeclaration",
                "add_accircmdeclaration",
                "view_acclocaltax",
                "add_acclocaltax",
            ],
        )
    )
    user.groups.add(group)
    return user


def test_dcom_generate_and_report_endpoints(a11_ledger, a11_user) -> None:
    tenant = a11_ledger["tenant"]
    fiscal_year = a11_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a11_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    generate_response = client.post(
        "/api/v1/accounting/reports/dcom/generate",
        {"fiscal_year_id": str(fiscal_year.id)},
        content_type="application/json",
        **headers,
    )
    assert generate_response.status_code == 200
    body = generate_response.json()
    assert body["total_amount_mga"] == "500000.0000"

    report_response = client.get(f"/api/v1/accounting/reports/dcom/{body['id']}", **headers)
    assert report_response.status_code == 200
    rows = report_response.json()
    assert len(rows) == 1
    assert rows[0]["classification"] == "tiers"


def test_ircm_generate_endpoint(a11_ledger, a11_user) -> None:
    tenant = a11_ledger["tenant"]
    fiscal_year = a11_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a11_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/accounting/reports/ircm/generate",
        {"fiscal_year_id": str(fiscal_year.id)},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["taxable_base_mga"] == "100000.0000"
    assert body["amount_due_mga"] == "20000.0000"


def test_local_taxes_create_and_list_endpoints(a11_ledger, a11_user) -> None:
    tenant = a11_ledger["tenant"]
    fiscal_year = a11_ledger["fiscal_year"]
    client = Client()
    token = _access_token(client, a11_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/accounting/local-taxes",
        {
            "tax_type": AccLocalTax.TAX_TYPE_IFT,
            "property_label": "Terrain nu",
            "assessed_value_mga": "50000000",
            "rate_pct": "1",
            "fiscal_year_id": str(fiscal_year.id),
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    assert create_response.json()["amount_due_mga"] == "500000.0000"

    list_response = client.get("/api/v1/accounting/local-taxes", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["results"]) == 1


def test_a11_endpoints_denied_for_commercial_role(a11_ledger) -> None:
    tenant = a11_ledger["tenant"]
    user = User.objects.create_user(email="a11-outsider@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/accounting/local-taxes", **headers)
    assert response.status_code == 403
