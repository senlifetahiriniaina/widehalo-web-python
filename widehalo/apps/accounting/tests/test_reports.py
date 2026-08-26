from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.invoices import (
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.accounting.services.reports import (
    general_ledger,
    invoice_pdf,
    journal_report,
    trial_balance,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-REP", name="Accounting Reports Tenant")
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
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        receivable = AccAccount.objects.create(
            tenant=tenant,
            code="411",
            name="Clients",
            account_class=4,
            type=AccAccount.TYPE_RECEIVABLE,
        )
        income = AccAccount.objects.create(
            tenant=tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        comptable = User.objects.create_user(email="rep@example.com", password="Str0ngPassw0rd!23")
        from django.contrib.auth.models import Group, Permission

        group, _ = Group.objects.get_or_create(name="comptable")
        group.permissions.add(
            Permission.objects.get(
                codename="validate_accmove", content_type__app_label="accounting"
            )
        )
        comptable.groups.add(group)
        ensure_default_approval_thresholds(tenant)

        invoice = create_invoice(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 15),
            partner_id=None,
            receivable_account=receivable,
            income_lines=[{"account": income, "amount": Decimal("1000"), "label": "Vente"}],
        )
        posted = validate_invoice(invoice, comptable)
        return tenant, fiscal_year, journal, receivable, income, posted


def test_trial_balance_lists_moved_accounts(ledger) -> None:
    tenant, fiscal_year, *_ = ledger
    with use_tenant(tenant.id):
        rows = trial_balance(fiscal_year)
        codes = {row["code"] for row in rows}
        assert {"411", "701"} <= codes
        receivable_row = next(row for row in rows if row["code"] == "411")
        assert receivable_row["debit"] == Decimal("1000.0000")


def test_general_ledger_lists_the_posted_line(ledger) -> None:
    tenant, fiscal_year, _journal, receivable, _income, invoice = ledger
    with use_tenant(tenant.id):
        rows = general_ledger(receivable, fiscal_year)
        assert len(rows) == 1
        assert rows[0]["reference"] == invoice.reference


def test_journal_report_lists_all_lines_of_the_journal(ledger) -> None:
    tenant, fiscal_year, journal, *_ = ledger
    with use_tenant(tenant.id):
        rows = journal_report(journal, fiscal_year)
        assert len(rows) == 2  # ligne client + ligne vente


def test_invoice_pdf_produces_a_valid_pdf_document(ledger) -> None:
    tenant, _fy, _journal, _receivable, _income, invoice = ledger
    with use_tenant(tenant.id):
        pdf_bytes = invoice_pdf(invoice)
        assert pdf_bytes.startswith(b"%PDF")
