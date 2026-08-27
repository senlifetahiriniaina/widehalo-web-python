"""A15 — endpoints API pour ACC-TRESO/ACC-REL/reconciliation mobile money."""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccJournal,
    AccPayment,
    AccPeriod,
)
from apps.accounting.services.dunning import seed_default_dunning_levels
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


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-A15-API", name="A15 API Tenant")
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
        bank = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )

        opening = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 1)
        )
        add_line(opening, account=bank, label="Apport", debit=Decimal("1000"))
        add_line(opening, account=equity, label="Apport", credit=Decimal("1000"))
        post_move(opening)

        overdue_move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 1)
        )
        add_line(
            overdue_move,
            account=receivable,
            label="Creance",
            debit=Decimal("2000"),
            due_date=dt.date(2026, 1, 1),
        )
        add_line(overdue_move, account=income, label="Vente", credit=Decimal("2000"))
        post_move(overdue_move)
        move_line = overdue_move.lines.get(account=receivable)

    return {"tenant": tenant, "move_line": move_line}


@pytest.fixture
def a15_user():
    user = User.objects.create_user(email="a15-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="accounting-a15-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=[
                "view_accaccount",
                "view_accdunninglevel",
                "add_accdunninglevel",
                "view_accmove",
                "add_accdunningaction",
                "add_accmobilemoneystatementline",
                "change_accmobilemoneystatementline",
                "view_accmobilemoneystatementline",
            ],
        )
    )
    user.groups.add(group)
    return user


def test_treasury_forecast_endpoint_flags_a_dip(ledger, a15_user) -> None:
    tenant = ledger["tenant"]
    client = Client()
    token = _access_token(client, a15_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        "/api/v1/accounting/reports/treasury-forecast?as_of_date=2026-01-05", **headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["starting_cash_mga"] == "1000.0000"
    assert len(data["buckets"]) == 13


def test_dunning_levels_endpoint_seeds_defaults(ledger, a15_user) -> None:
    tenant = ledger["tenant"]
    client = Client()
    token = _access_token(client, a15_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/accounting/dunning-levels/seed", content_type="application/json", **headers
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [row["level"] for row in results] == [1, 2, 3]

    listing = client.get("/api/v1/accounting/dunning-levels", **headers)
    assert listing.status_code == 200
    assert len(listing.json()["results"]) == 3


def test_overdue_receivables_and_dunning_action_endpoints(ledger, a15_user) -> None:
    tenant = ledger["tenant"]
    move_line = ledger["move_line"]
    client = Client()
    token = _access_token(client, a15_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        levels = seed_default_dunning_levels(tenant)

    response = client.get(
        "/api/v1/accounting/reports/overdue-receivables?as_of_date=2026-06-01", **headers
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["amount_mga"] == "2000.0000"

    action_response = client.post(
        "/api/v1/accounting/dunning-actions",
        {
            "move_line_id": str(move_line.id),
            "level_id": str(levels[1].id),
            "notes": "Appel telephonique",
        },
        content_type="application/json",
        **headers,
    )
    assert action_response.status_code == 200
    assert action_response.json()["notes"] == "Appel telephonique"


def test_mobile_money_import_reconcile_and_unmatched_endpoints(ledger, a15_user) -> None:
    tenant = ledger["tenant"]
    client = Client()
    token = _access_token(client, a15_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    csv_bytes = b"date,reference,amount,direction\n2026-02-01,MVOLA-1,5000,in\n"
    upload = io.BytesIO(csv_bytes)
    upload.name = "statement.csv"
    import_response = client.post(
        "/api/v1/accounting/mobile-money/import", {"statement": upload}, **headers
    )
    assert import_response.status_code == 200
    lines = import_response.json()["results"]
    assert len(lines) == 1
    line_id = lines[0]["id"]

    unmatched_response = client.get("/api/v1/accounting/mobile-money/unmatched", **headers)
    assert len(unmatched_response.json()["results"]) == 1

    with use_tenant(tenant.id):
        payment = AccPayment.objects.create(
            tenant=tenant,
            journal=AccJournal.objects.get(tenant=tenant),
            date=dt.date(2026, 2, 1),
            amount=Decimal("5000"),
            direction=AccPayment.DIRECTION_INBOUND,
            method=AccPayment.METHOD_MOBILE_MONEY,
        )

    reconcile_response = client.post(
        f"/api/v1/accounting/mobile-money/{line_id}/reconcile",
        {"payment_id": str(payment.id)},
        content_type="application/json",
        **headers,
    )
    assert reconcile_response.status_code == 200
    assert reconcile_response.json()["state"] == "matched"

    unmatched_after = client.get("/api/v1/accounting/mobile-money/unmatched", **headers)
    assert unmatched_after.json()["results"] == []
