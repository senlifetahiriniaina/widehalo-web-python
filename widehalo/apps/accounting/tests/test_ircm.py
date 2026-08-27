"""A11 — ACC-IRCM (`services/ircm.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccIrcmDeclaration,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.ircm import generate_ircm_declaration
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def ircm_ledger():
    tenant = Tenant.objects.create(
        code="ACC-IRCM", name="IRCM Tenant", fiscal_regime=Tenant.FISCAL_REGIME_REAL_WITH_VAT
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
            tenant=tenant, code="OD", name="OD", type=AccJournal.TYPE_MISC, sequence_prefix="OD"
        )
        bank_account = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        financial_income_account = _make_account(
            tenant,
            code="762",
            name="Revenus des creances",
            account_class=7,
            type=AccAccount.TYPE_INCOME,
        )

        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 10)
        )
        add_line(move, account=bank_account, label="Interets recus", debit=Decimal("100000"))
        add_line(
            move,
            account=financial_income_account,
            label="Interets recus",
            credit=Decimal("100000"),
        )
        post_move(move)

        return {"tenant": tenant, "fiscal_year": fiscal_year}


def test_generate_ircm_declaration_computes_amount_due_from_financial_income(ircm_ledger) -> None:
    fiscal_year = ircm_ledger["fiscal_year"]
    with use_tenant(ircm_ledger["tenant"].id):
        declaration = generate_ircm_declaration(fiscal_year)
        assert declaration.reference
        assert declaration.taxable_base_mga == Decimal("100000.0000")
        assert declaration.rate_pct == Decimal("20")
        assert declaration.amount_due_mga == Decimal("20000.0000")
        assert declaration.state == AccIrcmDeclaration.STATE_DRAFT


def test_generate_ircm_declaration_is_idempotent_per_fiscal_year(ircm_ledger) -> None:
    fiscal_year = ircm_ledger["fiscal_year"]
    with use_tenant(ircm_ledger["tenant"].id):
        first = generate_ircm_declaration(fiscal_year)
        second = generate_ircm_declaration(fiscal_year)
        assert first.id == second.id
        assert AccIrcmDeclaration.objects.filter(fiscal_year=fiscal_year).count() == 1


def test_generate_ircm_declaration_rejects_synthetic_regime_tenant() -> None:
    tenant = Tenant.objects.create(
        code="ACC-IRCM-SYNTH",
        name="IRCM Synthetique Tenant",
        fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC,
    )
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        with pytest.raises(ValidationError):
            generate_ircm_declaration(fiscal_year)
