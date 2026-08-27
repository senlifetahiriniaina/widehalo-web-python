"""A15 — ACC-TRESO (previsionnel de tresorerie + detection de creux),
ACC-REL (relances client a 3 niveaux, RG-ACC-11), reconciliation mobile
money simple."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccDunningAction,
    AccDunningLevel,
    AccFiscalYear,
    AccJournal,
    AccMobileMoneyStatementLine,
    AccPayment,
    AccPeriod,
)
from apps.accounting.services.dunning import (
    overdue_receivables,
    record_dunning_action,
    seed_default_dunning_levels,
)
from apps.accounting.services.mobile_money import (
    import_mobile_money_statement,
    reconcile_mobile_money_line,
    unmatched_mobile_money_lines,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.services.reports import treasury_forecast
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def bare_ledger():
    tenant = Tenant.objects.create(code="ACC-A15", name="Accounting A15 Tenant")
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
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        return tenant, fiscal_year, period, journal


# ---------------------------------------------------------------------------
# ACC-TRESO — treasury_forecast
# ---------------------------------------------------------------------------


def test_treasury_forecast_detects_a_dip_in_the_first_week(bare_ledger) -> None:
    tenant, fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        bank = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        payable = _make_account(
            tenant,
            code="401",
            name="Fournisseurs",
            account_class=4,
            type=AccAccount.TYPE_PAYABLE,
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        expense = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )

        as_of = dt.date(2026, 1, 5)

        # Position de depart : 1000 MGA en banque, constatee avant as_of.
        opening = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 2)
        )
        add_line(opening, account=bank, label="Apport", debit=Decimal("1000"))
        add_line(opening, account=equity, label="Apport", credit=Decimal("1000"))
        post_move(opening)

        # Dette fournisseur de 5000 MGA due dans 3 jours (semaine 1) : plus
        # grande que la position de depart -> creux attendu semaine 1.
        payable_move = create_draft_move(tenant=tenant, journal=journal, period=period, date=as_of)
        add_line(
            payable_move,
            account=expense,
            label="Achat",
            debit=Decimal("5000"),
        )
        add_line(
            payable_move,
            account=payable,
            label="Dette",
            credit=Decimal("5000"),
            due_date=as_of + dt.timedelta(days=3),
        )
        post_move(payable_move)

        # Creance client de 6000 MGA due dans 10 jours (semaine 2) : suffit a
        # repasser positif des la semaine 2.
        receivable_move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=as_of
        )
        add_line(
            receivable_move,
            account=receivable,
            label="Creance",
            debit=Decimal("6000"),
            due_date=as_of + dt.timedelta(days=10),
        )
        add_line(receivable_move, account=income, label="Vente", credit=Decimal("6000"))
        post_move(receivable_move)

        data = treasury_forecast(tenant, as_of_date=as_of, horizon_days=90)

        assert data["starting_cash_mga"] == Decimal("1000")
        assert len(data["buckets"]) == 13  # ceil(90 / 7)

        week1, week2 = data["buckets"][0], data["buckets"][1]
        assert week1["outflows_mga"] == Decimal("5000")
        assert week1["projected_balance_mga"] == Decimal("-4000")
        assert week2["inflows_mga"] == Decimal("6000")
        assert week2["projected_balance_mga"] == Decimal("2000")

        assert data["has_dip"] is True
        assert len(data["dips"]) == 1
        assert data["dips"][0]["period_label"] == week1["period_label"]
        assert data["dips"][0]["projected_balance_mga"] == Decimal("-4000")


def test_treasury_forecast_reports_no_dip_when_cash_stays_positive(bare_ledger) -> None:
    tenant, fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        bank = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )

        as_of = dt.date(2026, 1, 5)
        opening = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 2)
        )
        add_line(opening, account=bank, label="Apport", debit=Decimal("10000"))
        add_line(opening, account=equity, label="Apport", credit=Decimal("10000"))
        post_move(opening)

        data = treasury_forecast(tenant, as_of_date=as_of, horizon_days=90)
        assert data["has_dip"] is False
        assert data["dips"] == []
        assert all(b["projected_balance_mga"] == Decimal("10000") for b in data["buckets"])


# ---------------------------------------------------------------------------
# ACC-REL — relances client a 3 niveaux
# ---------------------------------------------------------------------------


def test_seed_default_dunning_levels_is_idempotent(bare_ledger) -> None:
    tenant, _fiscal_year, _period, _journal = bare_ledger
    with use_tenant(tenant.id):
        levels = seed_default_dunning_levels(tenant)
        assert [entry.level for entry in levels] == [1, 2, 3]
        assert AccDunningLevel.objects.count() == 3

        seed_default_dunning_levels(tenant)
        assert AccDunningLevel.objects.count() == 3


def test_overdue_receivables_assigns_the_applicable_level(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        seed_default_dunning_levels(tenant)
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        as_of = dt.date(2026, 6, 1)
        partner_overdue_level_2 = uuid.uuid4()
        partner_not_yet_due_for_level_1 = uuid.uuid4()

        def post_receivable(amount, due_date, partner_id):
            move = create_draft_move(tenant=tenant, journal=journal, period=period, date=as_of)
            add_line(
                move,
                account=receivable,
                label="Creance",
                debit=Decimal(amount),
                due_date=due_date,
                partner_id=partner_id,
            )
            add_line(move, account=income, label="Vente", credit=Decimal(amount))
            return post_move(move)

        # 40 jours de retard -> niveau 2 (>=30, <60).
        post_receivable(1000, as_of - dt.timedelta(days=40), partner_overdue_level_2)
        # 10 jours de retard -> pas encore le seuil du niveau 1 (15 jours).
        post_receivable(500, as_of - dt.timedelta(days=10), partner_not_yet_due_for_level_1)

        rows = {r["partner_id"]: r for r in overdue_receivables(tenant, as_of_date=as_of)}

        assert rows[partner_overdue_level_2]["days_overdue"] == 40
        assert rows[partner_overdue_level_2]["applicable_level"] == 2
        assert rows[partner_overdue_level_2]["amount_mga"] == Decimal("1000")

        assert rows[partner_not_yet_due_for_level_1]["days_overdue"] == 10
        assert rows[partner_not_yet_due_for_level_1]["applicable_level"] is None


def test_record_dunning_action_logs_a_traceable_reminder(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        levels = seed_default_dunning_levels(tenant)
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 1)
        )
        add_line(move, account=receivable, label="Creance", debit=Decimal("1000"))
        add_line(move, account=income, label="Vente", credit=Decimal("1000"))
        post_move(move)
        move_line = move.lines.get(account=receivable)

        action = record_dunning_action(
            move_line, levels[0], date_sent=dt.date(2026, 3, 1), notes="Appele le client"
        )

        assert isinstance(action, AccDunningAction)
        assert action.move_line_id == move_line.id
        assert action.level_id == levels[0].id
        assert action.date_sent == dt.date(2026, 3, 1)
        assert action.notes == "Appele le client"


# ---------------------------------------------------------------------------
# Reconciliation mobile money simple
# ---------------------------------------------------------------------------


_SAMPLE_CSV = (
    b"date,reference,amount,direction\n2026-02-01,MVOLA-1,5000,in\n2026-02-02,MVOLA-2,2000,out\n"
)


def test_import_mobile_money_statement_creates_unmatched_lines(bare_ledger) -> None:
    tenant, _fiscal_year, _period, _journal = bare_ledger
    with use_tenant(tenant.id):
        lines = import_mobile_money_statement(tenant, _SAMPLE_CSV)

        assert len(lines) == 2
        batch_ids = {line.import_batch_id for line in lines}
        assert len(batch_ids) == 1
        assert all(line.state == AccMobileMoneyStatementLine.STATE_UNMATCHED for line in lines)
        amounts = sorted(line.amount_mga for line in lines)
        assert amounts == [Decimal("2000"), Decimal("5000")]


def test_import_mobile_money_statement_rejects_an_invalid_direction(bare_ledger) -> None:
    tenant, _fiscal_year, _period, _journal = bare_ledger
    with use_tenant(tenant.id):
        bad_csv = b"date,reference,amount,direction\n2026-02-01,MVOLA-1,5000,sideways\n"
        with pytest.raises(ValidationError):
            import_mobile_money_statement(tenant, bad_csv)


def test_reconcile_mobile_money_line_requires_a_mobile_money_payment(bare_ledger) -> None:
    tenant, _fiscal_year, _period, journal = bare_ledger
    with use_tenant(tenant.id):
        (statement_line,) = import_mobile_money_statement(
            tenant, b"date,reference,amount,direction\n2026-02-01,MVOLA-1,5000,in\n"
        )
        cash_payment = AccPayment.objects.create(
            tenant=tenant,
            journal=journal,
            date=dt.date(2026, 2, 1),
            amount=Decimal("5000"),
            direction=AccPayment.DIRECTION_INBOUND,
            method=AccPayment.METHOD_CASH,
        )

        with pytest.raises(ValidationError):
            reconcile_mobile_money_line(statement_line, cash_payment)

        statement_line.refresh_from_db()
        assert statement_line.state == AccMobileMoneyStatementLine.STATE_UNMATCHED


def test_reconcile_mobile_money_line_matches_a_mobile_money_payment(bare_ledger) -> None:
    tenant, _fiscal_year, _period, journal = bare_ledger
    with use_tenant(tenant.id):
        (statement_line,) = import_mobile_money_statement(
            tenant, b"date,reference,amount,direction\n2026-02-01,MVOLA-1,5000,in\n"
        )
        mobile_money_payment = AccPayment.objects.create(
            tenant=tenant,
            journal=journal,
            date=dt.date(2026, 2, 1),
            amount=Decimal("5000"),
            direction=AccPayment.DIRECTION_INBOUND,
            method=AccPayment.METHOD_MOBILE_MONEY,
        )

        reconciled = reconcile_mobile_money_line(statement_line, mobile_money_payment)

        assert reconciled.state == AccMobileMoneyStatementLine.STATE_MATCHED
        assert reconciled.matched_payment_id == mobile_money_payment.id

        assert list(unmatched_mobile_money_lines(tenant)) == []
