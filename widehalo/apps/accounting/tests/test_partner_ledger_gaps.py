from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccMove
from apps.accounting.services.moves import add_line, create_draft_move
from apps.accounting.services.public import (
    list_customer_invoices_for_partner,
    list_ledger_entries_for_partner,
    list_supplier_invoices_for_partner,
)
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_list_ledger_entries_for_partner_returns_lines_for_that_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
        account = AccAccountFactory(tenant=tenant)
        partner_id = uuid.uuid4()

        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=period.date_start
        )
        add_line(
            move=move,
            account=account,
            label="Vente",
            debit=Decimal("100.0000"),
            credit=Decimal("0.0000"),
            partner_id=partner_id,
        )

        rows = list_ledger_entries_for_partner(partner_id)
        assert len(rows) == 1
        assert rows[0]["move_id"] == move.id
        assert rows[0]["debit"] == Decimal("100.0000")

        assert list_ledger_entries_for_partner(uuid.uuid4()) == []


def test_list_customer_and_supplier_invoices_for_partner_filter_by_move_type() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
        partner_id = uuid.uuid4()

        customer_move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=period.date_start
        )
        customer_move.move_type = AccMove.TYPE_CUSTOMER_INVOICE
        customer_move.partner_id = partner_id
        customer_move.save(update_fields=["move_type", "partner_id"])

        supplier_move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=period.date_start
        )
        supplier_move.move_type = AccMove.TYPE_SUPPLIER_INVOICE
        supplier_move.partner_id = partner_id
        supplier_move.save(update_fields=["move_type", "partner_id"])

        customer_rows = list_customer_invoices_for_partner(partner_id)
        assert [row["id"] for row in customer_rows] == [customer_move.id]

        supplier_rows = list_supplier_invoices_for_partner(partner_id)
        assert [row["id"] for row in supplier_rows] == [supplier_move.id]
