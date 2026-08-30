"""AI3 : adaptateur `apps.accounting.services.ai_anomaly_registration` —
verifie que le check REEL (pas un fake) enregistre dans
`core.services.anomaly_registry` surfacce effectivement un ecart
budgetaire significatif a partir de donnees comptables reelles (budget
approuve + ecriture postee), en reutilisant `services/budgets.py`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.ai_anomaly_registration import _check_budget_variance
from apps.accounting.services.budgets import add_budget_line, approve_budget, create_budget
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.services.anomaly_registry import SEVERITY_HIGH, get_anomaly_check
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("accounting.budget_variance")
    assert registered is not None
    assert registered.module == "accounting"
    assert registered.function is _check_budget_variance


def test_check_surfaces_a_real_high_variance_from_a_posted_ledger() -> None:
    tenant = Tenant.objects.create(code="ACC-AI3", name="Accounting AI3 Tenant")
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
        achats = AccAccount.objects.create(
            tenant=tenant,
            code="601",
            name="Achats",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        bank = AccAccount.objects.create(
            tenant=tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )

        budget = create_budget(tenant=tenant, fiscal_year=fiscal_year, name="Budget 2026")
        add_budget_line(budget, account=achats, period=period, budgeted_amount_mga=Decimal("10000"))
        approve_budget(budget)

        # Reel : 20 000 contre un budget de 10 000 -> ecart de 100%, HIGH.
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=period.date_start
        )
        add_line(move, account=achats, label="Achat", debit=Decimal("20000"))
        add_line(move, account=bank, label="Banque", credit=Decimal("20000"))
        post_move(move)

        candidates = _check_budget_variance(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "accounting.accbudgetline"
    assert candidate.severity == SEVERITY_HIGH
    assert "601" in candidate.description


def test_check_returns_nothing_when_variance_stays_below_threshold() -> None:
    tenant = Tenant.objects.create(code="ACC-AI3-OK", name="Accounting AI3 OK Tenant")
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
        achats = AccAccount.objects.create(
            tenant=tenant,
            code="601",
            name="Achats",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        bank = AccAccount.objects.create(
            tenant=tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )

        budget = create_budget(tenant=tenant, fiscal_year=fiscal_year, name="Budget 2026")
        add_budget_line(budget, account=achats, period=period, budgeted_amount_mga=Decimal("10000"))
        approve_budget(budget)

        # Reel : 10 500 contre un budget de 10 000 -> ecart de 5%, sous le
        # seuil MEDIUM (20%) : aucune anomalie ne doit etre remontee.
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=period.date_start
        )
        add_line(move, account=achats, label="Achat", debit=Decimal("10500"))
        add_line(move, account=bank, label="Banque", credit=Decimal("10500"))
        post_move(move)

        candidates = _check_budget_variance(str(tenant.id))

    assert candidates == []
