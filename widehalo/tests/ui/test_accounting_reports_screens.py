from __future__ import annotations

import datetime as dt

import pytest
from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccMoveLine,
    AccPeriod,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def accounting_reports_setup():
    tenant = Tenant.objects.create(code="UI-ACC-RPT", name="UI Accounting Reports Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-acc-rpt@example.com", password="Str0ngPassw0rd!23"
        )
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="2026",
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
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        receivable = AccAccount.objects.create(
            tenant=tenant, code="411000", name="Clients", account_class="4", type="receivable"
        )
        income = AccAccount.objects.create(
            tenant=tenant, code="701000", name="Ventes", account_class="7", type="income"
        )
        move = AccMove.objects.create(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 15),
            move_type=AccMove.TYPE_CUSTOMER_INVOICE,
            reference="VTE/2026/0001",
            state=AccMove.STATE_POSTED,
            currency="MGA",
        )
        AccMoveLine.objects.create(
            tenant=tenant,
            move=move,
            account=receivable,
            label="Vente tissus",
            debit=500000,
            credit=0,
        )
        AccMoveLine.objects.create(
            tenant=tenant, move=move, account=income, label="Vente tissus", debit=0, credit=500000
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, fiscal_year, journal, receivable


def test_reports_index_screen_renders(accounting_reports_setup) -> None:
    client, _tenant, _fiscal_year, _journal, _receivable = accounting_reports_setup
    response = client.get("/accounting/reports/")
    assert response.status_code == 200


def test_trial_balance_download_json(accounting_reports_setup) -> None:
    client, _tenant, fiscal_year, _journal, _receivable = accounting_reports_setup
    response = client.get(
        "/accounting/reports/trial-balance/", {"fiscal_year_id": str(fiscal_year.id)}
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response["Content-Disposition"].startswith("attachment;")
    assert b"411000" in response.content


def test_general_ledger_download_json(accounting_reports_setup) -> None:
    client, _tenant, fiscal_year, _journal, receivable = accounting_reports_setup
    response = client.get(
        "/accounting/reports/general-ledger/",
        {"account_id": str(receivable.id), "fiscal_year_id": str(fiscal_year.id)},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"Vente tissus" in response.content


def test_journal_report_download_json(accounting_reports_setup) -> None:
    client, _tenant, fiscal_year, journal, _receivable = accounting_reports_setup
    response = client.get(
        "/accounting/reports/journal/",
        {"journal_id": str(journal.id), "fiscal_year_id": str(fiscal_year.id)},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"VTE/2026/0001" in response.content
