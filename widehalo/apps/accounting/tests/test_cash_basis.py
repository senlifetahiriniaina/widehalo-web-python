from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.cash_basis import record_cash_movement
from apps.accounting.services.reports import cash_basis_report
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def cash_ledger():
    tenant = Tenant.objects.create(
        code="ACC-SMT", name="Synthetique Tenant", fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC
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
            tenant=tenant,
            code="CAI",
            name="Caisse",
            type=AccJournal.TYPE_CASH,
            sequence_prefix="CAI",
        )
        cash_account = AccAccount.objects.create(
            tenant=tenant, code="571", name="Caisse", account_class=5, type=AccAccount.TYPE_CASH
        )
        income_account = AccAccount.objects.create(
            tenant=tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        expense_account = AccAccount.objects.create(
            tenant=tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        return tenant, fiscal_year, period, journal, cash_account, income_account, expense_account


def test_record_cash_movement_in_produces_a_balanced_posted_move(cash_ledger) -> None:
    tenant, _fy, period, journal, cash_account, income_account, _expense = cash_ledger
    with use_tenant(tenant.id):
        move = record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 5),
            direction="in",
            amount=Decimal("50000"),
            cash_or_bank_account=cash_account,
            counterpart_account=income_account,
            label="Vente comptant",
        )
        assert move.state == AccMove.STATE_POSTED
        assert move.total_debit == move.total_credit == Decimal("50000.0000")
        cash_line = move.lines.get(account=cash_account)
        income_line = move.lines.get(account=income_account)
        assert cash_line.debit == Decimal("50000.0000")
        assert cash_line.credit == Decimal("0.0000")
        assert income_line.credit == Decimal("50000.0000")
        assert income_line.debit == Decimal("0.0000")


def test_record_cash_movement_out_produces_a_balanced_posted_move(cash_ledger) -> None:
    tenant, _fy, period, journal, cash_account, _income, expense_account = cash_ledger
    with use_tenant(tenant.id):
        move = record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 10),
            direction="out",
            amount=Decimal("15000"),
            cash_or_bank_account=cash_account,
            counterpart_account=expense_account,
            label="Achat fournitures",
        )
        assert move.state == AccMove.STATE_POSTED
        assert move.total_debit == move.total_credit == Decimal("15000.0000")
        cash_line = move.lines.get(account=cash_account)
        expense_line = move.lines.get(account=expense_account)
        assert cash_line.credit == Decimal("15000.0000")
        assert expense_line.debit == Decimal("15000.0000")


def test_record_cash_movement_rejects_non_cash_or_bank_account(cash_ledger) -> None:
    tenant, _fy, period, journal, _cash, income_account, expense_account = cash_ledger
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 10),
            direction="out",
            amount=Decimal("1000"),
            cash_or_bank_account=expense_account,
            counterpart_account=income_account,
        )


def test_record_cash_movement_rejects_non_positive_amount(cash_ledger) -> None:
    tenant, _fy, period, journal, cash_account, income_account, _expense = cash_ledger
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 10),
            direction="in",
            amount=Decimal("0"),
            cash_or_bank_account=cash_account,
            counterpart_account=income_account,
        )


def test_cash_basis_report_recap_mode_lists_flat_movements(cash_ledger) -> None:
    tenant, fiscal_year, period, journal, cash_account, income_account, expense_account = (
        cash_ledger
    )
    with use_tenant(tenant.id):
        record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 5),
            direction="in",
            amount=Decimal("50000"),
            cash_or_bank_account=cash_account,
            counterpart_account=income_account,
            label="Vente comptant",
        )
        record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 10),
            direction="out",
            amount=Decimal("15000"),
            cash_or_bank_account=cash_account,
            counterpart_account=expense_account,
            label="Achat fournitures",
        )

        rows = cash_basis_report(fiscal_year, mode="recap")
        assert len(rows) == 2
        assert "balance" not in rows[0]
        assert rows[0]["direction"] == "in"
        assert rows[0]["amount"] == Decimal("50000.0000")
        assert rows[1]["direction"] == "out"
        assert rows[1]["amount"] == Decimal("15000.0000")


def test_cash_basis_report_smt_mode_adds_running_balance(cash_ledger) -> None:
    tenant, fiscal_year, period, journal, cash_account, income_account, expense_account = (
        cash_ledger
    )
    with use_tenant(tenant.id):
        record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 5),
            direction="in",
            amount=Decimal("50000"),
            cash_or_bank_account=cash_account,
            counterpart_account=income_account,
        )
        record_cash_movement(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 10),
            direction="out",
            amount=Decimal("15000"),
            cash_or_bank_account=cash_account,
            counterpart_account=expense_account,
        )

        rows = cash_basis_report(fiscal_year, mode="smt")
        assert rows[0]["balance"] == Decimal("50000.0000")
        assert rows[1]["balance"] == Decimal("35000.0000")


def test_cash_basis_report_rejects_unknown_mode(cash_ledger) -> None:
    tenant, fiscal_year, *_ = cash_ledger
    with use_tenant(tenant.id), pytest.raises(ValueError):
        cash_basis_report(fiscal_year, mode="bogus")
