"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `accounting` — CHECK/trigger de partie-double et
d'immuabilite deja couverts par `test_moves.py` (RG-ACC-1/RG-ACC-2, non
reproduits ici). Ce fichier comble le reste : `UniqueConstraint` et
comportement `on_delete` (PROTECT/CASCADE/SET_NULL) de chaque FK du modele.

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError

from apps.accounting.models import (
    AccAnalyticAccount,
    AccAnalyticLine,
    AccExchangeRate,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccPaymentAllocation,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccAnalyticAccountFactory,
    AccAnalyticLineFactory,
    AccAnalyticPlanFactory,
    AccExchangeRateFactory,
    AccJournalFactory,
    AccMoveFactory,
    AccMoveLineFactory,
    AccPaymentAllocationFactory,
    AccPaymentFactory,
    AccPeriodFactory,
    AccTaxFactory,
)
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# UniqueConstraint
# --------------------------------------------------------------------------


def test_exchange_rate_unique_per_tenant_currency_date() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        AccExchangeRateFactory(
            tenant=tenant, currency="USD", date=dt.date(2026, 1, 1), rate_to_mga=Decimal("4500")
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            AccExchangeRate.objects.create(
                tenant=tenant,
                currency="USD",
                date=dt.date(2026, 1, 1),
                rate_to_mga=Decimal("4600"),
            )


def test_analytic_account_unique_code_per_plan() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        plan = AccAnalyticPlanFactory(tenant=tenant)
        AccAnalyticAccountFactory(tenant=tenant, plan=plan, code="PRJ-1")

        with pytest.raises(IntegrityError), transaction.atomic():
            AccAnalyticAccount.objects.create(
                tenant=tenant, plan=plan, code="PRJ-1", name="Doublon"
            )


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_journal_cannot_be_deleted_while_referenced_by_a_move() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        move = AccMoveFactory(tenant=tenant)
        journal = move.journal

        with pytest.raises(ProtectedError):
            journal.delete()


def test_period_cannot_be_deleted_while_referenced_by_a_move() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        move = AccMoveFactory(tenant=tenant)
        period = move.period

        with pytest.raises(ProtectedError):
            period.delete()


def test_account_cannot_be_deleted_while_referenced_by_a_move_line() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = AccMoveLineFactory(tenant=tenant)
        account = line.account

        with pytest.raises(ProtectedError):
            account.delete()


def test_journal_cannot_be_deleted_while_referenced_by_a_payment() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        payment = AccPaymentFactory(tenant=tenant)
        journal = payment.journal

        with pytest.raises(ProtectedError):
            journal.delete()


def test_move_cannot_be_deleted_while_referenced_by_a_payment() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        move = AccMoveFactory(tenant=tenant)
        payment = AccPaymentFactory(tenant=tenant, move=move)

        with pytest.raises(ProtectedError):
            move.delete()

        assert AccPayment.objects.filter(pk=payment.pk).exists()


def test_move_line_cannot_be_deleted_while_allocated_to_a_payment() -> None:
    """RG-ACC-8 : une ligne lettree (partiellement ou totalement) ne peut
    pas disparaitre sous une allocation de paiement existante."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        allocation = AccPaymentAllocationFactory(tenant=tenant)
        move_line = allocation.move_line

        with pytest.raises(ProtectedError):
            move_line.delete()


def test_tax_cannot_be_deleted_while_referenced_by_a_move_line() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        tax = AccTaxFactory(tenant=tenant)
        AccMoveLineFactory(tenant=tenant, tax=tax)

        with pytest.raises(ProtectedError):
            tax.delete()


def test_analytic_account_cannot_be_deleted_while_referenced_by_an_analytic_line() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        analytic_line = AccAnalyticLineFactory(tenant=tenant)
        analytic_account = analytic_line.analytic_account

        with pytest.raises(ProtectedError):
            analytic_account.delete()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_deleting_a_draft_move_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = AccMoveLineFactory(tenant=tenant)
        move = line.move
        line_id = line.id

        move.delete()

        assert not AccMoveLine.objects.filter(pk=line_id).exists()


def test_deleting_a_payment_cascades_to_its_allocations() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        allocation = AccPaymentAllocationFactory(tenant=tenant)
        payment = allocation.payment
        allocation_id = allocation.id

        payment.delete()

        assert not AccPaymentAllocation.objects.filter(pk=allocation_id).exists()


def test_deleting_a_fiscal_year_cascades_to_its_periods() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        period = AccPeriodFactory(tenant=tenant)
        fiscal_year = period.fiscal_year
        period_id = period.id

        fiscal_year.delete()

        from apps.accounting.models import AccPeriod

        assert not AccPeriod.objects.filter(pk=period_id).exists()


def test_deleting_a_plan_cascades_to_its_analytic_accounts() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        analytic_account = AccAnalyticAccountFactory(tenant=tenant)
        plan = analytic_account.plan
        analytic_account_id = analytic_account.id

        plan.delete()

        assert not AccAnalyticAccount.objects.filter(pk=analytic_account_id).exists()


def test_deleting_a_move_line_cascades_to_its_analytic_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        analytic_line = AccAnalyticLineFactory(tenant=tenant)
        move_line = analytic_line.move_line
        analytic_line_id = analytic_line.id

        move_line.delete()

        assert not AccAnalyticLine.objects.filter(pk=analytic_line_id).exists()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_parent_account_nullifies_children() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        parent = AccAccountFactory(tenant=tenant, code="6")
        child = AccAccountFactory(tenant=tenant, code="60", parent=parent)

        parent.delete()
        child.refresh_from_db()

        assert child.parent_id is None


def test_deleting_a_parent_analytic_account_nullifies_children() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        plan = AccAnalyticPlanFactory(tenant=tenant)
        parent = AccAnalyticAccountFactory(tenant=tenant, plan=plan, code="PRJ")
        child = AccAnalyticAccountFactory(tenant=tenant, plan=plan, code="PRJ-A", parent=parent)

        parent.delete()
        child.refresh_from_db()

        assert child.parent_id is None


def test_deleting_a_journals_default_account_nullifies_the_journal() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        account = AccAccountFactory(tenant=tenant)
        journal = AccJournalFactory(tenant=tenant, default_account=account)

        account.delete()
        journal.refresh_from_db()

        assert journal.default_account_id is None


def test_deleting_a_taxs_accounts_nullifies_the_tax() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        collected = AccAccountFactory(tenant=tenant)
        deductible = AccAccountFactory(tenant=tenant)
        tax = AccTaxFactory(
            tenant=tenant, account_collected=collected, account_deductible=deductible
        )

        collected.delete()
        deductible.delete()
        tax.refresh_from_db()

        assert tax.account_collected_id is None
        assert tax.account_deductible_id is None


def test_deleting_a_reconciled_line_nullifies_the_reconciliation_link() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        origin = AccMoveLineFactory(tenant=tenant)
        matched = AccMoveLineFactory(tenant=tenant, reconciled_with=origin)

        origin.delete()
        matched.refresh_from_db()

        assert matched.reconciled_with_id is None


def test_deleting_a_reversed_move_is_protected() -> None:
    """`AccMove.reverses` est PROTECT : l'ecriture d'origine d'une extourne
    ne doit jamais pouvoir disparaitre tant que l'extourne existe (tracabilite
    RG-ACC-2)."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        original = AccMoveFactory(tenant=tenant)
        AccMove.objects.create(
            tenant=tenant,
            journal=original.journal,
            period=original.period,
            date=original.date,
            move_type=AccMove.TYPE_ENTRY,
            reverses=original,
        )

        with pytest.raises(ProtectedError):
            original.delete()
