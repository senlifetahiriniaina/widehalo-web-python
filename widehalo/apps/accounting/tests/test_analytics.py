from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccAnalyticPlan,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.analytics import record_analytic_lines, validate_distribution
from apps.accounting.services.moves import add_line, create_draft_move
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-ANA", name="Accounting Analytics Tenant")
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
        expense = AccAccount.objects.create(
            tenant=tenant,
            code="601",
            name="Achats",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
            analytic_required=True,
        )
        optional_expense = AccAccount.objects.create(
            tenant=tenant,
            code="613",
            name="Locations",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        cash = AccAccount.objects.create(
            tenant=tenant, code="530", name="Caisse", account_class=5, type=AccAccount.TYPE_CASH
        )
        plan = AccAnalyticPlan.objects.create(tenant=tenant, code="atelier", name="Atelier")
        analytic_account = AccAnalyticAccount.objects.create(
            tenant=tenant, plan=plan, code="AT-ANTS", name="Atelier Antananarivo"
        )
        return tenant, period, journal, expense, optional_expense, cash, plan, analytic_account


def test_distribution_summing_to_100_is_valid() -> None:
    validate_distribution({"atelier": {"AT-ANTS": 60, "AT-TOAM": 40}})


def test_distribution_not_summing_to_100_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_distribution({"atelier": {"AT-ANTS": 60, "AT-TOAM": 30}})


def test_analytic_required_account_rejects_empty_distribution(ledger) -> None:
    tenant, period, journal, expense, _optional, cash, *_ = ledger
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        with pytest.raises(ValidationError):
            add_line(move, account=expense, debit=Decimal("1000"))


def test_analytic_required_account_accepts_a_valid_distribution(ledger) -> None:
    tenant, period, journal, expense, _optional, cash, plan, analytic_account = ledger
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        line = add_line(
            move,
            account=expense,
            debit=Decimal("1000"),
            analytic_distribution={"atelier": {"AT-ANTS": 100}},
        )
        assert line.analytic_distribution == {"atelier": {"AT-ANTS": 100}}


def test_optional_analytic_account_accepts_empty_distribution(ledger) -> None:
    tenant, period, journal, _expense, optional_expense, cash, *_ = ledger
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        line = add_line(move, account=optional_expense, debit=Decimal("500"))
        assert line.analytic_distribution == {}


def test_record_analytic_lines_materializes_amounts(ledger) -> None:
    tenant, period, journal, expense, _optional, cash, plan, analytic_account = ledger
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        line = add_line(
            move,
            account=expense,
            debit=Decimal("1000"),
            analytic_distribution={"atelier": {"AT-ANTS": 100}},
        )

        analytic_lines = record_analytic_lines(line)

        assert len(analytic_lines) == 1
        assert analytic_lines[0].analytic_account_id == analytic_account.id
        assert analytic_lines[0].amount == Decimal("1000.0000")
