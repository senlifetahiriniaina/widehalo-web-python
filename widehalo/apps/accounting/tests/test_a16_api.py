"""A16 — endpoints API pour le rapprochement bancaire assiste par regles."""

from __future__ import annotations

import datetime as dt
import io
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


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-A16-API", name="A16 API Tenant")
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
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
        )
        add_line(move, account=bank, label="Virement", debit=Decimal("5000"))
        add_line(move, account=equity, label="Contrepartie", credit=Decimal("5000"))
        post_move(move)
        move_line = move.lines.get(account=bank)

    return {"tenant": tenant, "bank": bank, "move_line": move_line}


@pytest.fixture
def a16_user():
    user = User.objects.create_user(email="a16-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="accounting-a16-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=[
                "view_accreconcilerule",
                "add_accreconcilerule",
                "add_accbankstatementline",
                "change_accbankstatementline",
                "view_accbankstatementline",
            ],
        )
    )
    user.groups.add(group)
    return user


def test_reconcile_rule_create_and_list_endpoints(ledger, a16_user) -> None:
    tenant = ledger["tenant"]
    client = Client()
    token = _access_token(client, a16_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/accounting/reconcile-rules",
        {"name": "Montant seul", "match_on_amount": True, "priority": 5},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Montant seul"

    listing = client.get("/api/v1/accounting/reconcile-rules", **headers)
    assert listing.status_code == 200
    assert len(listing.json()["results"]) == 1


def test_bank_reconciliation_full_flow_endpoints(ledger, a16_user) -> None:
    tenant = ledger["tenant"]
    bank = ledger["bank"]
    move_line = ledger["move_line"]
    client = Client()
    token = _access_token(client, a16_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    client.post(
        "/api/v1/accounting/reconcile-rules",
        {"name": "Montant seul", "match_on_amount": True},
        content_type="application/json",
        **headers,
    )

    csv_bytes = b"date,reference,label,amount,direction\n2026-02-01,VIR-1,Virement,5000,in\n"
    upload = io.BytesIO(csv_bytes)
    upload.name = "statement.csv"
    import_response = client.post(
        f"/api/v1/accounting/bank-reconciliation/import?bank_account_id={bank.id}",
        {"statement": upload},
        **headers,
    )
    assert import_response.status_code == 200
    lines = import_response.json()["results"]
    assert len(lines) == 1
    line_id = lines[0]["id"]

    unmatched_response = client.get(
        f"/api/v1/accounting/bank-reconciliation/{bank.id}/unmatched", **headers
    )
    assert len(unmatched_response.json()["results"]) == 1

    suggest_response = client.post(
        f"/api/v1/accounting/bank-reconciliation/{bank.id}/suggest-matches",
        content_type="application/json",
        **headers,
    )
    assert suggest_response.status_code == 200
    suggested = suggest_response.json()["results"]
    assert len(suggested) == 1
    assert suggested[0]["state"] == "rule_suggested"
    assert suggested[0]["matched_move_line_id"] == str(move_line.id)

    confirm_response = client.post(
        f"/api/v1/accounting/bank-reconciliation/{line_id}/confirm",
        {},
        content_type="application/json",
        **headers,
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["state"] == "matched"

    unmatched_after = client.get(
        f"/api/v1/accounting/bank-reconciliation/{bank.id}/unmatched", **headers
    )
    assert unmatched_after.json()["results"] == []


def test_manual_match_endpoint_without_any_rule(ledger, a16_user) -> None:
    tenant = ledger["tenant"]
    bank = ledger["bank"]
    move_line = ledger["move_line"]
    client = Client()
    token = _access_token(client, a16_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    csv_bytes = b"date,reference,label,amount,direction\n2026-02-01,VIR-1,Sans rapport,5000,in\n"
    upload = io.BytesIO(csv_bytes)
    upload.name = "statement.csv"
    import_response = client.post(
        f"/api/v1/accounting/bank-reconciliation/import?bank_account_id={bank.id}",
        {"statement": upload},
        **headers,
    )
    line_id = import_response.json()["results"][0]["id"]

    manual_response = client.post(
        f"/api/v1/accounting/bank-reconciliation/{line_id}/manual-match",
        {"move_line_id": str(move_line.id)},
        content_type="application/json",
        **headers,
    )
    assert manual_response.status_code == 200
    assert manual_response.json()["state"] == "matched"
    assert manual_response.json()["matched_move_line_id"] == str(move_line.id)
