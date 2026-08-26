from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccExchangeRate,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccPeriod,
)
from apps.accounting.services.invoices import (
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.accounting.services.payments import outstanding_balance, register_payment
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _grant(user: User, group_name: str, *codenames: str) -> None:
    group, _ = Group.objects.get_or_create(name=group_name)
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="accounting")
        group.permissions.add(permission)
    user.groups.add(group)


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-PAY", name="Accounting Payments Tenant")
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
        sales_journal = AccJournal.objects.create(
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        bank_journal = AccJournal.objects.create(
            tenant=tenant, code="BQ", name="Banque", type=AccJournal.TYPE_BANK, sequence_prefix="BQ"
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
        bank = AccAccount.objects.create(
            tenant=tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        gain = AccAccount.objects.create(
            tenant=tenant,
            code="766",
            name="Gains de change",
            account_class=7,
            type=AccAccount.TYPE_INCOME,
        )
        loss = AccAccount.objects.create(
            tenant=tenant,
            code="666",
            name="Pertes de change",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        comptable = User.objects.create_user(
            email="comptable-pay@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(comptable, "comptable", "validate_accmove")
        ensure_default_approval_thresholds(tenant)
        return {
            "tenant": tenant,
            "period": period,
            "sales_journal": sales_journal,
            "bank_journal": bank_journal,
            "receivable": receivable,
            "income": income,
            "bank": bank,
            "gain": gain,
            "loss": loss,
            "comptable": comptable,
        }


def _posted_invoice(ctx, amount=Decimal("1000"), currency="MGA"):
    invoice = create_invoice(
        tenant=ctx["tenant"],
        journal=ctx["sales_journal"],
        period=ctx["period"],
        date=dt.date(2026, 1, 15),
        partner_id=None,
        receivable_account=ctx["receivable"],
        income_lines=[{"account": ctx["income"], "amount": amount, "label": "Vente"}],
        currency=currency,
    )
    return validate_invoice(invoice, ctx["comptable"])


def test_full_mga_payment_settles_the_invoice(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        invoice = _posted_invoice(ledger, Decimal("1000"))
        payment = register_payment(
            invoice=invoice,
            period=ledger["period"],
            journal=ledger["bank_journal"],
            cash_account=ledger["bank"],
            gain_account=ledger["gain"],
            loss_account=ledger["loss"],
            date=dt.date(2026, 1, 20),
            amount=Decimal("1000"),
            method="virement",
        )
        invoice.refresh_from_db()
        assert invoice.invoice_state == AccMove.INVOICE_STATE_PAID
        assert outstanding_balance(invoice.lines.filter(debit__gt=0).first()) == Decimal(0)
        assert payment.state == "posted"


def test_partial_payment_leaves_a_residual_balance(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        invoice = _posted_invoice(ledger, Decimal("1000"))
        register_payment(
            invoice=invoice,
            period=ledger["period"],
            journal=ledger["bank_journal"],
            cash_account=ledger["bank"],
            gain_account=ledger["gain"],
            loss_account=ledger["loss"],
            date=dt.date(2026, 1, 20),
            amount=Decimal("600"),
            method="virement",
        )
        invoice.refresh_from_db()
        receivable_line = invoice.lines.filter(debit__gt=0).first()
        assert invoice.invoice_state == AccMove.INVOICE_STATE_PAID_PARTIALLY
        assert outstanding_balance(receivable_line) == Decimal("400.0000")

        register_payment(
            invoice=invoice,
            period=ledger["period"],
            journal=ledger["bank_journal"],
            cash_account=ledger["bank"],
            gain_account=ledger["gain"],
            loss_account=ledger["loss"],
            date=dt.date(2026, 1, 25),
            amount=Decimal("400"),
            method="virement",
        )
        invoice.refresh_from_db()
        assert invoice.invoice_state == AccMove.INVOICE_STATE_PAID
        assert outstanding_balance(invoice.lines.filter(debit__gt=0).first()) == Decimal(0)


def test_payment_assigns_a_matching_number(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        invoice = _posted_invoice(ledger, Decimal("1000"))
        register_payment(
            invoice=invoice,
            period=ledger["period"],
            journal=ledger["bank_journal"],
            cash_account=ledger["bank"],
            gain_account=ledger["gain"],
            loss_account=ledger["loss"],
            date=dt.date(2026, 1, 20),
            amount=Decimal("1000"),
            method="virement",
        )
        receivable_line = invoice.lines.filter(debit__gt=0).first()
        assert receivable_line.matching_number != ""
        assert receivable_line.reconciled_with is not None


def test_foreign_currency_payment_at_a_different_rate_books_exchange_difference(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        AccExchangeRate.objects.create(
            tenant=ledger["tenant"],
            currency="EUR",
            date=dt.date(2026, 1, 15),
            rate_to_mga=Decimal("4800"),
        )
        AccExchangeRate.objects.create(
            tenant=ledger["tenant"],
            currency="EUR",
            date=dt.date(2026, 1, 20),
            rate_to_mga=Decimal("4850"),
        )
        invoice = _posted_invoice(ledger, Decimal("100"), currency="EUR")
        receivable_line = invoice.lines.filter(debit__gt=0).first()
        assert receivable_line.debit == Decimal("480000.0000")  # 100 EUR @ 4800

        register_payment(
            invoice=invoice,
            period=ledger["period"],
            journal=ledger["bank_journal"],
            cash_account=ledger["bank"],
            gain_account=ledger["gain"],
            loss_account=ledger["loss"],
            date=dt.date(2026, 1, 20),
            amount=Decimal("100"),
            method="virement",
        )
        invoice.refresh_from_db()
        assert invoice.invoice_state == AccMove.INVOICE_STATE_PAID

        from apps.accounting.models import AccMoveLine

        gain_move_line = AccMoveLine.objects.filter(account=ledger["gain"]).first()
        assert gain_move_line is not None
        assert gain_move_line.credit == Decimal("5000.0000")  # 100*(4850-4800)


def test_payment_on_a_non_posted_invoice_is_refused(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        invoice = create_invoice(
            tenant=ledger["tenant"],
            journal=ledger["sales_journal"],
            period=ledger["period"],
            date=dt.date(2026, 1, 15),
            partner_id=None,
            receivable_account=ledger["receivable"],
            income_lines=[
                {"account": ledger["income"], "amount": Decimal("1000"), "label": "Vente"}
            ],
        )
        with pytest.raises(ValidationError):
            register_payment(
                invoice=invoice,
                period=ledger["period"],
                journal=ledger["bank_journal"],
                cash_account=ledger["bank"],
                gain_account=ledger["gain"],
                loss_account=ledger["loss"],
                date=dt.date(2026, 1, 20),
                amount=Decimal("1000"),
                method="virement",
            )


def test_payment_amount_must_be_positive(ledger) -> None:
    with use_tenant(ledger["tenant"].id):
        invoice = _posted_invoice(ledger, Decimal("1000"))
        with pytest.raises(ValidationError):
            register_payment(
                invoice=invoice,
                period=ledger["period"],
                journal=ledger["bank_journal"],
                cash_account=ledger["bank"],
                gain_account=ledger["gain"],
                loss_account=ledger["loss"],
                date=dt.date(2026, 1, 20),
                amount=Decimal("0"),
                method="virement",
            )
