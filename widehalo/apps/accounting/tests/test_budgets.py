"""A14 — Budgets et analyse d'ecart (`acc_budget`/`acc_budget_line`,
comparaison reel vs budget)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccAnalyticPlan,
    AccBudget,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.analytics import record_analytic_lines
from apps.accounting.services.budgets import (
    add_budget_line,
    approve_budget,
    budget_variance_report,
    create_budget,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-A14", name="Accounting A14 Tenant")
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period_jan = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        period_feb = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-02",
            date_start=dt.date(2026, 2, 1),
            date_end=dt.date(2026, 2, 28),
        )
        journal = AccJournal.objects.create(
            tenant=tenant, code="OD", name="OD", type=AccJournal.TYPE_MISC, sequence_prefix="OD"
        )
        achats = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        personnel = _make_account(
            tenant,
            code="641",
            name="Charges de personnel",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        ventes = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        bank = _make_account(
            tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )
        plan = AccAnalyticPlan.objects.create(tenant=tenant, code="projet", name="Projet")
        p1 = AccAnalyticAccount.objects.create(tenant=tenant, plan=plan, code="P1", name="Projet 1")
    return {
        "tenant": tenant,
        "fiscal_year": fiscal_year,
        "period_jan": period_jan,
        "period_feb": period_feb,
        "journal": journal,
        "achats": achats,
        "personnel": personnel,
        "ventes": ventes,
        "bank": bank,
        "plan": plan,
        "p1": p1,
    }


def _post(
    ledger,
    period,
    date,
    *,
    debit_account,
    debit,
    credit_account,
    credit,
    distribution=None,
    distribution_on="debit",
):
    """Poste une ecriture equilibree. `distribution_on` selectionne quelle
    des deux lignes recoit la distribution analytique materialisee (la
    ligne dont le compte est effectivement sous test — cf. patron de
    `test_a13_ratios_and_analytics.py::analytic_ledger._posted_line`)."""
    move = create_draft_move(
        tenant=ledger["tenant"], journal=ledger["journal"], period=period, date=date
    )
    debit_line = add_line(
        move,
        account=debit_account,
        label="D",
        debit=Decimal(debit),
        analytic_distribution=distribution if distribution_on == "debit" else {},
    )
    credit_line = add_line(
        move,
        account=credit_account,
        label="C",
        credit=Decimal(credit),
        analytic_distribution=distribution if distribution_on == "credit" else {},
    )
    post_move(move)
    if distribution:
        record_analytic_lines(debit_line if distribution_on == "debit" else credit_line)
    return debit_line if distribution_on == "debit" else credit_line


def test_create_budget_starts_in_draft(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        budget = create_budget(
            tenant=ledger["tenant"], fiscal_year=ledger["fiscal_year"], name="Budget 2026"
        )
    assert budget.state == AccBudget.STATE_DRAFT
    assert budget.reference.startswith("BUD-2026-")


def test_add_budget_line_rejected_once_approved(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        budget = create_budget(
            tenant=ledger["tenant"], fiscal_year=ledger["fiscal_year"], name="Budget 2026"
        )
        approve_budget(budget)
        with pytest.raises(ValidationError):
            add_budget_line(budget, account=ledger["achats"], budgeted_amount_mga=Decimal(1000))


def test_approve_budget_rejects_double_approval(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        budget = create_budget(
            tenant=ledger["tenant"], fiscal_year=ledger["fiscal_year"], name="Budget 2026"
        )
        approve_budget(budget)
        with pytest.raises(ValidationError):
            approve_budget(budget)


def test_budget_variance_report_computes_actual_and_variance(ledger) -> None:
    """Trois lignes : une bornee a une periode precise, une etalee sur
    l'exercice (period=None), une avec axe analytique optionnel."""
    tenant = ledger["tenant"]
    with use_tenant(tenant.id):
        budget = create_budget(tenant=tenant, fiscal_year=ledger["fiscal_year"], name="Budget 2026")

        # Ligne 1 : achats, bornee a janvier, budget 10 000.
        line_period = add_budget_line(
            budget,
            account=ledger["achats"],
            period=ledger["period_jan"],
            budgeted_amount_mga=Decimal("10000"),
        )
        # Ligne 2 : personnel, etalee sur tout l'exercice, budget 5 000.
        line_full_year = add_budget_line(
            budget,
            account=ledger["personnel"],
            budgeted_amount_mga=Decimal("5000"),
        )
        # Ligne 3 : ventes, avec axe analytique P1, budget 8 000.
        line_analytic = add_budget_line(
            budget,
            account=ledger["ventes"],
            analytic_account=ledger["p1"],
            budgeted_amount_mga=Decimal("8000"),
        )
        approve_budget(budget)

        # Reel achats janvier : 12 000 (au-dessus du budget).
        _post(
            ledger,
            ledger["period_jan"],
            dt.date(2026, 1, 10),
            debit_account=ledger["achats"],
            debit=12_000,
            credit_account=ledger["bank"],
            credit=12_000,
        )
        # Reel achats fevrier : 3 000, HORS PERIODE de `line_period` (janvier
        # uniquement) — ne doit pas etre compte dans son ecart.
        _post(
            ledger,
            ledger["period_feb"],
            dt.date(2026, 2, 5),
            debit_account=ledger["achats"],
            debit=3_000,
            credit_account=ledger["bank"],
            credit=3_000,
        )
        # Reel personnel : 2 000 en janvier + 1 500 en fevrier = 4 500 sur
        # l'exercice entier (line_full_year n'a pas de periode : cumul total).
        _post(
            ledger,
            ledger["period_jan"],
            dt.date(2026, 1, 15),
            debit_account=ledger["personnel"],
            debit=2_000,
            credit_account=ledger["bank"],
            credit=2_000,
        )
        _post(
            ledger,
            ledger["period_feb"],
            dt.date(2026, 2, 10),
            debit_account=ledger["personnel"],
            debit=1_500,
            credit_account=ledger["bank"],
            credit=1_500,
        )
        # Reel ventes sur P1 : 9 000.
        _post(
            ledger,
            ledger["period_jan"],
            dt.date(2026, 1, 20),
            debit_account=ledger["bank"],
            debit=9_000,
            credit_account=ledger["ventes"],
            credit=9_000,
            distribution={"projet": {"P1": 100}},
            distribution_on="credit",
        )

        rows = budget_variance_report(budget)

    by_line = {row["account_code"]: row for row in rows}

    achats_row = by_line["601"]
    assert achats_row["period_label"] == "2026-01"
    assert achats_row["budgeted_amount_mga"] == Decimal("10000")
    assert achats_row["actual_amount_mga"] == Decimal("12000.0000")
    assert achats_row["variance_mga"] == Decimal("2000.0000")
    assert achats_row["variance_pct"] == Decimal("2000.0000") / Decimal("10000")

    personnel_row = by_line["641"]
    assert personnel_row["period_label"] is None
    assert personnel_row["actual_amount_mga"] == Decimal("3500.0000")
    assert personnel_row["variance_mga"] == Decimal("3500.0000") - Decimal("5000")

    ventes_row = by_line["701"]
    assert ventes_row["analytic_account_label"] == str(ledger["p1"])
    assert ventes_row["actual_amount_mga"] == Decimal("9000.0000")
    assert ventes_row["variance_mga"] == Decimal("9000.0000") - Decimal("8000")
    assert ventes_row["variance_pct"] == Decimal("1000.0000") / Decimal("8000")

    assert line_period.id and line_full_year.id and line_analytic.id


def test_budget_variance_report_variance_pct_is_none_when_budgeted_is_zero(ledger) -> None:
    tenant = ledger["tenant"]
    with use_tenant(tenant.id):
        budget = create_budget(tenant=tenant, fiscal_year=ledger["fiscal_year"], name="Budget 2026")
        add_budget_line(budget, account=ledger["achats"], budgeted_amount_mga=Decimal("0"))
        approve_budget(budget)

        rows = budget_variance_report(budget)

    assert rows[0]["budgeted_amount_mga"] == Decimal("0")
    assert rows[0]["actual_amount_mga"] == Decimal(0)
    assert rows[0]["variance_pct"] is None
