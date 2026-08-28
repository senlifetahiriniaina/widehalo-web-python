"""Tests du contrat public de `accounting` (`apps/accounting/services/
public.py`) — seule surface que `sales` (S4, RG-SAL-2) et `purchase` (PU6,
cf. plan) ont le droit d'importer. Couvre le gap ajoute pour la
facturation reelle depuis `sales.services.invoicing` :
`create_customer_invoice_from_source`, ainsi que les 3 gaps ajoutes par
PU6 de `purchase` : `create_supplier_invoice_from_source` (RG-PUR-6),
`create_landed_cost_batch_from_source` (RG-PUR-7),
`get_budget_variance_for_analytic_account` (PUR-BUD1)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import (
    AccAccount,
    AccBudget,
    AccJournal,
    AccLandedCostBatch,
    AccMove,
    AccPeriod,
)
from apps.accounting.services.public import (
    create_customer_invoice_from_source,
    create_landed_cost_batch_from_source,
    create_supplier_invoice_from_source,
    get_budget_variance_for_analytic_account,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccAnalyticAccountFactory,
    AccBudgetFactory,
    AccBudgetLineFactory,
    AccFiscalYearFactory,
    AccJournalFactory,
    AccPeriodFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_setup():
    tenant = Tenant.objects.create(code="ACC-PUB", name="Accounting Public Tenant")
    with use_tenant(tenant.id):
        return tenant


def _full_setup(tenant: Tenant) -> tuple[AccJournal, AccPeriod, AccAccount, AccAccount]:
    journal = AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    period = AccPeriodFactory(
        tenant=tenant,
        date_start=dt.date(2026, 1, 1),
        date_end=dt.date(2026, 1, 31),
    )
    receivable = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    income = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    return journal, period, receivable, income


def test_create_customer_invoice_from_source_success_path(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        _journal, _period, _receivable, income = _full_setup(tenant)
        partner_id = uuid.uuid4()

        move_id = create_customer_invoice_from_source(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 1, 15),
            income_lines=[
                {"account_id": income.id, "amount": Decimal("1000"), "label": "Vente"},
            ],
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        assert move.move_type == AccMove.TYPE_CUSTOMER_INVOICE
        assert move.state == AccMove.STATE_DRAFT
        assert move.invoice_state == AccMove.INVOICE_STATE_DRAFT
        assert move.partner_id == partner_id
        receivable_line = move.lines.get(account_id=_receivable.id)
        income_line = move.lines.get(account_id=income.id)
        assert receivable_line.debit == Decimal("1000")
        assert income_line.credit == Decimal("1000")


def test_create_customer_invoice_from_source_returns_none_without_sale_journal(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)

        move_id = create_customer_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            income_lines=[{"account_id": None, "amount": Decimal("500"), "label": "Vente"}],
        )

        assert move_id is None
        assert not AccMove.objects.exists()


def test_create_customer_invoice_from_source_returns_none_without_open_period(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)

        # Aucune periode ne couvre cette date.
        move_id = create_customer_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 6, 15),
            income_lines=[{"account_id": None, "amount": Decimal("500"), "label": "Vente"}],
        )

        assert move_id is None
        assert not AccMove.objects.exists()


def test_create_customer_invoice_from_source_returns_none_without_receivable_account(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)

        move_id = create_customer_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            income_lines=[{"account_id": None, "amount": Decimal("500"), "label": "Vente"}],
        )

        assert move_id is None
        assert not AccMove.objects.exists()


def test_create_customer_invoice_from_source_falls_back_to_default_income_account(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        _journal, _period, _receivable, income = _full_setup(tenant)

        move_id = create_customer_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            income_lines=[{"account_id": None, "amount": Decimal("750"), "label": "Vente"}],
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        income_line = move.lines.get(account_id=income.id)
        assert income_line.credit == Decimal("750")


def test_create_customer_invoice_from_source_returns_none_without_any_income_account(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)

        move_id = create_customer_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            income_lines=[{"account_id": None, "amount": Decimal("500"), "label": "Vente"}],
        )

        assert move_id is None
        assert not AccMove.objects.exists()


# ---------------------------------------------------------------------------
# PU6 (purchase) — RG-PUR-6 : create_supplier_invoice_from_source
# ---------------------------------------------------------------------------


def test_create_supplier_invoice_from_source_success_path(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PURCHASE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        payable = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)
        expense = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        partner_id = uuid.uuid4()

        move_id = create_supplier_invoice_from_source(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 1, 15),
            expense_lines=[
                {"account_id": expense.id, "amount": Decimal("1000"), "label": "Achat"},
            ],
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        assert move.move_type == AccMove.TYPE_SUPPLIER_INVOICE
        assert move.state == AccMove.STATE_DRAFT
        assert move.invoice_state == AccMove.INVOICE_STATE_DRAFT
        assert move.partner_id == partner_id
        payable_line = move.lines.get(account_id=payable.id)
        expense_line = move.lines.get(account_id=expense.id)
        assert payable_line.credit == Decimal("1000")
        assert expense_line.debit == Decimal("1000")


def test_create_supplier_invoice_from_source_falls_back_to_default_expense_account(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PURCHASE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)
        expense = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        move_id = create_supplier_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            expense_lines=[{"account_id": None, "amount": Decimal("750"), "label": "Achat"}],
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        expense_line = move.lines.get(account_id=expense.id)
        assert expense_line.debit == Decimal("750")


def test_create_supplier_invoice_from_source_returns_none_without_purchase_journal(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        move_id = create_supplier_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            expense_lines=[{"account_id": None, "amount": Decimal("500"), "label": "Achat"}],
        )

        assert move_id is None
        assert not AccMove.objects.exists()


def test_create_supplier_invoice_from_source_returns_none_without_payable_account(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PURCHASE)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        move_id = create_supplier_invoice_from_source(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date(2026, 1, 15),
            expense_lines=[{"account_id": None, "amount": Decimal("500"), "label": "Achat"}],
        )

        assert move_id is None
        assert not AccMove.objects.exists()


# ---------------------------------------------------------------------------
# PU6 (purchase) — RG-PUR-7 : create_landed_cost_batch_from_source
# ---------------------------------------------------------------------------


def test_create_landed_cost_batch_from_source_success_path(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()

        batch_id = create_landed_cost_batch_from_source(
            tenant=tenant,
            label="Import lot test",
            date=dt.date(2026, 1, 15),
            allocation_method=AccLandedCostBatch.METHOD_BY_VALUE,
            lines=[
                {
                    "description": "Tissu",
                    "qty": Decimal("100"),
                    "purchase_value_mga": Decimal("500000"),
                    "variant_id": variant_id,
                },
            ],
            cost_components=[{"label": "Fret", "amount_mga": Decimal("50000")}],
        )

        assert batch_id is not None
        batch = AccLandedCostBatch.objects.get(id=batch_id)
        assert batch.total_purchase_value_mga == Decimal("500000")
        assert batch.lines.count() == 1
        assert batch.cost_components.count() == 1
        assert batch.cost_components.first().amount_mga == Decimal("50000")


def test_create_landed_cost_batch_from_source_returns_none_without_lines(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        batch_id = create_landed_cost_batch_from_source(
            tenant=tenant,
            label="Lot vide",
            date=dt.date(2026, 1, 15),
            allocation_method=AccLandedCostBatch.METHOD_BY_VALUE,
            lines=[],
            cost_components=[],
        )

        assert batch_id is None
        assert not AccLandedCostBatch.objects.exists()


# ---------------------------------------------------------------------------
# PUR-BUD1 (purchase) : get_budget_variance_for_analytic_account
# ---------------------------------------------------------------------------


def test_get_budget_variance_for_analytic_account_aggregates_matching_lines(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYearFactory(tenant=tenant)
        analytic_account = AccAnalyticAccountFactory(tenant=tenant)
        budget = AccBudgetFactory(
            tenant=tenant, fiscal_year=fiscal_year, state=AccBudget.STATE_APPROVED
        )
        AccBudgetLineFactory(
            tenant=tenant,
            budget=budget,
            analytic_account=analytic_account,
            budgeted_amount_mga=Decimal("100000"),
        )
        AccBudgetLineFactory(
            tenant=tenant,
            budget=budget,
            analytic_account=analytic_account,
            budgeted_amount_mga=Decimal("50000"),
        )

        result = get_budget_variance_for_analytic_account(
            tenant=tenant, analytic_account_id=analytic_account.id
        )

        assert result is not None
        assert result["budgeted_amount_mga"] == Decimal("150000")
        assert result["actual_amount_mga"] == Decimal("0")
        assert result["variance_mga"] == Decimal("-150000")
        assert result["variance_pct"] == Decimal("-150000") / Decimal("150000")


def test_get_budget_variance_for_analytic_account_ignores_draft_budget(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYearFactory(tenant=tenant)
        analytic_account = AccAnalyticAccountFactory(tenant=tenant)
        budget = AccBudgetFactory(
            tenant=tenant, fiscal_year=fiscal_year, state=AccBudget.STATE_DRAFT
        )
        AccBudgetLineFactory(
            tenant=tenant,
            budget=budget,
            analytic_account=analytic_account,
            budgeted_amount_mga=Decimal("100000"),
        )

        result = get_budget_variance_for_analytic_account(
            tenant=tenant, analytic_account_id=analytic_account.id
        )

        assert result is None


def test_get_budget_variance_for_analytic_account_returns_none_without_match(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        result = get_budget_variance_for_analytic_account(
            tenant=tenant, analytic_account_id=uuid.uuid4()
        )

        assert result is None
