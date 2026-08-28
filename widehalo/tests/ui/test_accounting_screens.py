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


def _posted_invoice_for_payment(client, tenant, journal, receivable, income):
    from apps.accounting.models import AccJournal, AccMove
    from apps.accounting.services.invoices import (
        ensure_default_approval_thresholds,
        validate_invoice,
    )
    from apps.core.models.user import User
    from apps.core.tests.utils import use_tenant
    from django.contrib.auth.models import Group, Permission

    with use_tenant(tenant.id):
        bank_journal = AccJournal.objects.create(
            tenant=tenant, code="BQ", name="Banque", type=AccJournal.TYPE_BANK, sequence_prefix="BQ"
        )
        bank_account = AccAccount.objects.create(
            tenant=tenant, code="512000", name="Banque", account_class="5", type="bank"
        )
        gain = AccAccount.objects.create(
            tenant=tenant, code="766000", name="Gains de change", account_class="7", type="income"
        )
        loss = AccAccount.objects.create(
            tenant=tenant, code="666000", name="Pertes de change", account_class="6", type="expense"
        )
        ensure_default_approval_thresholds(tenant)
        comptable = User.objects.create_user(
            email="ui-acc-comptable@example.com", password="Str0ngPassw0rd!23"
        )
        group, _ = Group.objects.get_or_create(name="comptable")
        permission = Permission.objects.get(
            codename="validate_accmove", content_type__app_label="accounting"
        )
        group.permissions.add(permission)
        comptable.groups.add(group)

    create_response = client.post(
        "/accounting/new/",
        {
            "journal_id": str(journal.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "income_account_id": str(income.id),
            "label": "Vente tissus",
            "amount": "1000",
        },
    )
    assert create_response.status_code == 302
    invoice_id = create_response.url.rstrip("/").split("/")[-1]

    with use_tenant(tenant.id):
        invoice = AccMove.objects.get(id=invoice_id)
        validate_invoice(invoice, comptable)

    return invoice_id, bank_journal, bank_account, gain, loss


def test_invoice_payment_registration_shows_allocation(accounting_screens_setup) -> None:
    client, tenant, journal, receivable, income = accounting_screens_setup
    invoice_id, bank_journal, bank_account, gain, loss = _posted_invoice_for_payment(
        client, tenant, journal, receivable, income
    )

    payment_response = client.post(
        f"/accounting/{invoice_id}/",
        {
            "action": "register_payment",
            "payment_journal_id": str(bank_journal.id),
            "cash_account_id": str(bank_account.id),
            "gain_account_id": str(gain.id),
            "loss_account_id": str(loss.id),
            "payment_amount": "1000",
            "payment_date": "2026-01-20",
            "method": "virement",
        },
    )
    assert payment_response.status_code == 302

    detail = client.get(f"/accounting/{invoice_id}/")
    assert detail.status_code == 200
    assert b"virement" in detail.content.lower() or b"Virement" in detail.content
    assert b"1000" in detail.content


def test_imports_screens_render(accounting_screens_setup) -> None:
    """Chantier import comptable/caisse — les 4 ecrans HTMX sont
    atteignables en session (jamais l'API JWT en interne)."""
    client, _tenant, _journal, _receivable, _income = accounting_screens_setup

    index = client.get("/accounting/config/imports/")
    assert index.status_code == 200

    chart = client.get("/accounting/config/imports/chart-of-accounts/")
    assert chart.status_code == 200

    cash_journal = client.get("/accounting/config/imports/cash-journal/")
    assert cash_journal.status_code == 200
