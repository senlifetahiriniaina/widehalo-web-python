"""Tests du contrat public de `accounting` (`apps/accounting/services/
public.py`) — seule surface que `sales` (S4, RG-SAL-2) a le droit
d'importer. Couvre le gap ajoute pour la facturation reelle depuis
`sales.services.invoicing` : `create_customer_invoice_from_source`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccPeriod
from apps.accounting.services.public import create_customer_invoice_from_source
from apps.accounting.tests.factories import (
    AccAccountFactory,
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
