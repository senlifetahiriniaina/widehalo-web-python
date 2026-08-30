"""INT1 (chantier interactivite native inter-modules) : evenements
`accounting.invoice_validated`/`accounting.invoice_cancelled` — absents de
`services/invoices.py` jusqu'ici (verifie par lecture directe)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.invoices import (
    cancel_invoice,
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.core.models.event import EventLog
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
    tenant = Tenant.objects.create(code="ACC-INT1-INV", name="Accounting INT1 Invoices Tenant")
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
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
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
        ensure_default_approval_thresholds(tenant)
        return tenant, period, journal, receivable, income


def _make_invoice(ledger, amount: Decimal):
    tenant, period, journal, receivable, income = ledger
    return create_invoice(
        tenant=tenant,
        journal=journal,
        period=period,
        date=dt.date(2026, 1, 15),
        partner_id=None,
        receivable_account=receivable,
        income_lines=[{"account": income, "amount": amount, "label": "Vente"}],
    )


def test_validate_invoice_publishes_invoice_validated(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="int1-comptable@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(user, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("500000"))
        posted = validate_invoice(invoice, user)
        assert posted.state == AccMove.STATE_POSTED

    event = EventLog.objects.get(
        event_type="accounting.invoice_validated", tenant_id=str(tenant.id)
    )
    assert event.payload["move_id"] == str(posted.id)


def test_cancel_invoice_publishes_invoice_cancelled(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(
            email="int1-c4@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(comptable, "comptable", "cancel_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))
        cancelled = cancel_invoice(invoice, comptable, motif="Erreur de saisie")
        assert cancelled.invoice_state == AccMove.INVOICE_STATE_CANCELLED

    event = EventLog.objects.get(
        event_type="accounting.invoice_cancelled", tenant_id=str(tenant.id)
    )
    assert event.payload["move_id"] == str(cancelled.id)
    assert event.payload["motif"] == "Erreur de saisie"
