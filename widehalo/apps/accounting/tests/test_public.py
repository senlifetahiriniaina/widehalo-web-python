"""Tests du contrat public de `accounting` (`apps/accounting/services/
public.py`) — seule surface que `sales` (S4, RG-SAL-2) et `purchase` (PU6,
cf. plan) ont le droit d'importer. Couvre le gap ajoute pour la
facturation reelle depuis `sales.services.invoicing` :
`create_customer_invoice_from_source`, ainsi que les 3 gaps ajoutes par
PU6 de `purchase` : `create_supplier_invoice_from_source` (RG-PUR-6),
`create_landed_cost_batch_from_source` (RG-PUR-7),
`get_budget_variance_for_analytic_account` (PUR-BUD1), et le gap ajoute
par ST5 de `stocks` : `create_stock_movement_entry_from_source`
(RG-STK-9 ; renommee et generalisee par A3, Phase 3 §5.8, STK-12, pour
couvrir aussi les mouvements de stock ordinaires en plus de l'ajustement
d'inventaire)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccBudget,
    AccJournal,
    AccLandedCostBatch,
    AccMove,
    AccPaymentTerm,
    AccPeriod,
    AccTax,
)
from apps.accounting.services.public import (
    create_customer_invoice_from_source,
    create_landed_cost_batch_from_source,
    create_pos_session_closing_entry_from_source,
    create_stock_movement_entry_from_source,
    create_supplier_invoice_from_source,
    get_budget_variance_for_analytic_account,
    get_default_sale_tax,
    get_treasury_forecast_summary,
    list_payment_terms,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccAnalyticAccountFactory,
    AccBudgetFactory,
    AccBudgetLineFactory,
    AccFiscalYearFactory,
    AccJournalFactory,
    AccPeriodFactory,
    AccTaxFactory,
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


def test_create_stock_movement_entry_from_source_success_path(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        move_id = create_stock_movement_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            lines=[
                {"account_id": None, "amount": Decimal("10000"), "label": "Entree ajustement"},
                {"account_id": None, "amount": Decimal("-10000"), "label": "Ecart d'inventaire"},
            ],
            label="STKINV-2026-0001",
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        assert move.move_type == AccMove.TYPE_ENTRY
        assert move.state == AccMove.STATE_POSTED
        assert move.total_debit == Decimal("10000.0000")
        assert move.total_credit == Decimal("10000.0000")
        debit_line = move.lines.get(debit__gt=0)
        credit_line = move.lines.get(credit__gt=0)
        assert debit_line.account.type == AccAccount.TYPE_STOCK
        assert credit_line.account.type == AccAccount.TYPE_EXPENSE


def test_create_stock_movement_entry_from_source_negative_amount_credits(public_setup) -> None:
    """Ecart negatif (sortie) : la resolution du compte par defaut se fait
    par SIGNE de la ligne, jamais par position dans la liste — la ligne
    positive (debit) retombe toujours sur le compte de stock, la ligne
    negative (credit) toujours sur le compte de charge, quel que soit
    l'ordre passe par l'appelant (ici l'inverse de l'entree : la ligne
    negative est fournie EN PREMIER)."""
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        move_id = create_stock_movement_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            lines=[
                {"account_id": None, "amount": Decimal("-5000"), "label": "Sortie ajustement"},
                {"account_id": None, "amount": Decimal("5000"), "label": "Ecart d'inventaire"},
            ],
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        credit_line = move.lines.get(credit__gt=0)
        debit_line = move.lines.get(debit__gt=0)
        # Positif=debit -> compte stock ; negatif=credit -> compte charge,
        # independamment de l'ordre des lignes en entree.
        assert debit_line.account.type == AccAccount.TYPE_STOCK
        assert credit_line.account.type == AccAccount.TYPE_EXPENSE


def test_create_stock_movement_entry_from_source_refuses_unbalanced_lines(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        with pytest.raises(ValidationError):
            create_stock_movement_entry_from_source(
                tenant=tenant,
                date=dt.date(2026, 1, 15),
                lines=[
                    {"account_id": None, "amount": Decimal("10000"), "label": "Entree"},
                    {"account_id": None, "amount": Decimal("-9000"), "label": "Ecart"},
                ],
            )


def test_create_stock_movement_entry_from_source_returns_none_without_stock_journal(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        result = create_stock_movement_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            lines=[
                {"account_id": None, "amount": Decimal("1000"), "label": "Entree"},
                {"account_id": None, "amount": Decimal("-1000"), "label": "Ecart"},
            ],
        )

        assert result is None


def test_create_stock_movement_entry_from_source_returns_none_without_open_period(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        result = create_stock_movement_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            lines=[
                {"account_id": None, "amount": Decimal("1000"), "label": "Entree"},
                {"account_id": None, "amount": Decimal("-1000"), "label": "Ecart"},
            ],
        )

        assert result is None


def test_get_treasury_forecast_summary_delegates_to_treasury_forecast(public_setup) -> None:
    """Nouveau gap ajoute pendant le chantier `strategy` (rapport business
    plan, ACC-TRESO) — simple passe-plat, verifie ici sur un tenant sans
    aucun mouvement (solde de depart et paniers a zero, jamais une
    exception)."""
    tenant = public_setup
    with use_tenant(tenant.id):
        result = get_treasury_forecast_summary(
            tenant, as_of_date=dt.date(2026, 6, 1), horizon_days=90
        )
        assert result["starting_cash_mga"] == Decimal(0)
        assert result["dips"] == []


def test_create_stock_movement_entry_from_source_returns_none_without_stock_account(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)

        result = create_stock_movement_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            lines=[
                {"account_id": None, "amount": Decimal("1000"), "label": "Entree"},
                {"account_id": None, "amount": Decimal("-1000"), "label": "Ecart"},
            ],
        )

        assert result is None


def test_list_payment_terms_returns_primitives_ordered_by_name(public_setup) -> None:
    """DT5 (gap accounting pour `sales`) : `list_payment_terms` ne renvoie
    que des primitives (id/name), jamais un objet `AccPaymentTerm` Django —
    regle de couplage n1."""
    tenant = public_setup
    with use_tenant(tenant.id):
        AccPaymentTerm.objects.create(tenant=tenant, name="60 jours fin de mois")
        AccPaymentTerm.objects.create(tenant=tenant, name="Comptant")
        inactive = AccPaymentTerm.objects.create(tenant=tenant, name="Terme archive")
        inactive.soft_delete()

        result = list_payment_terms(tenant)

    assert [row["name"] for row in result] == ["60 jours fin de mois", "Comptant"]
    assert all(isinstance(row, dict) for row in result)


def test_get_default_sale_tax_returns_the_first_valid_sale_tax(public_setup) -> None:
    """Gap ajoute pour le module `pos` (§13.5)."""
    tenant = public_setup
    with use_tenant(tenant.id):
        account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX)
        AccTaxFactory(
            tenant=tenant,
            type=AccTax.TYPE_SALE,
            code="TVA1",
            rate=Decimal("20.000"),
            account_collected=account,
        )

        result = get_default_sale_tax(tenant, on_date=dt.date(2026, 1, 15))

    assert result is not None
    assert result["rate"] == Decimal("20.000")
    assert result["account_id"] == account.id


def test_get_default_sale_tax_ignores_taxes_outside_their_validity_window(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        AccTaxFactory(
            tenant=tenant,
            type=AccTax.TYPE_SALE,
            rate=Decimal("18.000"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )

        result = get_default_sale_tax(tenant, on_date=dt.date(2026, 1, 15))

    assert result is None


def test_get_default_sale_tax_returns_none_without_any_sale_tax(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        result = get_default_sale_tax(tenant, on_date=dt.date(2026, 1, 15))

    assert result is None


def _pos_closing_setup(tenant: Tenant) -> tuple[AccAccount, AccAccount, AccAccount, AccAccount]:
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_CASH)
    AccPeriodFactory(tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31))
    cash = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_CASH)
    income = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    tax = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX)
    expense = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
    return cash, income, tax, expense


def test_create_pos_session_closing_entry_from_source_success_path(public_setup) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        cash, income, tax, _expense = _pos_closing_setup(tenant)

        move_id = create_pos_session_closing_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            payment_totals=[
                {"account_id": None, "default_account_type": "cash", "amount": Decimal("12000")}
            ],
            income_amount_mga=Decimal("10000"),
            tax_amount_mga=Decimal("2000"),
            cash_variance_mga=Decimal("0"),
            label="Clôture caisse CAISSE-1",
        )

        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        assert move.state == AccMove.STATE_POSTED
        assert move.total_debit == move.total_credit == Decimal("12000.0000")
        assert move.lines.get(account_id=cash.id).debit == Decimal("12000")
        assert move.lines.get(account_id=income.id).credit == Decimal("10000")
        assert move.lines.get(account_id=tax.id).credit == Decimal("2000")


def test_create_pos_session_closing_entry_from_source_books_a_shortage_as_an_expense(
    public_setup,
) -> None:
    """Écart NÉGATIF (manquant en caisse) : ligne de débit supplémentaire
    sur le compte de charge — l'écriture reste équilibrée malgré le
    montant COMPTÉ (12000-500=11500) inférieur au théorique (10000+2000)."""
    tenant = public_setup
    with use_tenant(tenant.id):
        cash, income, tax, expense = _pos_closing_setup(tenant)

        move_id = create_pos_session_closing_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            payment_totals=[
                {"account_id": None, "default_account_type": "cash", "amount": Decimal("11500")}
            ],
            income_amount_mga=Decimal("10000"),
            tax_amount_mga=Decimal("2000"),
            cash_variance_mga=Decimal("-500"),
        )

        move = AccMove.objects.get(id=move_id)
        assert move.total_debit == move.total_credit == Decimal("12000.0000")
        variance_line = move.lines.get(account_id=expense.id)
        assert variance_line.debit == Decimal("500")
        assert variance_line.credit == Decimal("0")


def test_create_pos_session_closing_entry_from_source_books_a_surplus_as_income(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        cash, income, tax, _expense = _pos_closing_setup(tenant)

        move_id = create_pos_session_closing_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            payment_totals=[
                {"account_id": None, "default_account_type": "cash", "amount": Decimal("12500")}
            ],
            income_amount_mga=Decimal("10000"),
            tax_amount_mga=Decimal("2000"),
            cash_variance_mga=Decimal("500"),
        )

        move = AccMove.objects.get(id=move_id)
        assert move.total_debit == move.total_credit == Decimal("12500.0000")
        # Le compte "income" porte a la fois le produit des ventes (10000)
        # et le surplus de caisse (500) — deux lignes distinctes sur le
        # meme compte (aucune consolidation, chaque ligne garde son
        # libelle propre).
        income_lines = move.lines.filter(account_id=income.id)
        assert income_lines.count() == 2
        assert sum((line.credit for line in income_lines), Decimal(0)) == Decimal("10500")


def test_create_pos_session_closing_entry_from_source_returns_none_without_cash_journal(
    public_setup,
) -> None:
    tenant = public_setup
    with use_tenant(tenant.id):
        result = create_pos_session_closing_entry_from_source(
            tenant=tenant,
            date=dt.date(2026, 1, 15),
            payment_totals=[],
            income_amount_mga=Decimal("0"),
            tax_amount_mga=Decimal("0"),
            cash_variance_mga=Decimal("0"),
        )

    assert result is None
