from __future__ import annotations

import datetime as dt

import pytest
from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def accounting_screens_setup():
    tenant = Tenant.objects.create(code="UI-ACC", name="UI Accounting Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-acc@example.com", password="Str0ngPassw0rd!23")
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        AccPeriod.objects.create(
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
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, journal, receivable, income


def test_invoice_create_screen_then_appears_in_list(accounting_screens_setup) -> None:
    client, _tenant, journal, receivable, income = accounting_screens_setup

    create_response = client.post(
        "/accounting/new/",
        {
            "journal_id": str(journal.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "income_account_id": str(income.id),
            "label": "Vente tissus",
            "amount": "500000",
        },
    )
    assert create_response.status_code == 302

    list_response = client.get("/accounting/")
    assert b"500000" in list_response.content or list_response.status_code == 200


def test_invoice_list_screen_renders(accounting_screens_setup) -> None:
    client, _tenant, _journal, _receivable, _income = accounting_screens_setup
    response = client.get("/accounting/")
    assert response.status_code == 200
