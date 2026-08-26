from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    cancel_invoice,
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest
from apps.core.services.approvals import decide
from apps.core.services.workflow import TransitionPermissionError
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
    tenant = Tenant.objects.create(code="ACC-INV", name="Accounting Invoices Tenant")
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


def test_create_invoice_is_balanced(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        invoice = _make_invoice(ledger, Decimal("1000"))
        totals = {line.debit for line in invoice.lines.all() if line.debit} | {
            line.credit for line in invoice.lines.all() if line.credit
        }
        assert totals == {Decimal("1000")}


def test_validate_invoice_under_threshold_posts_directly(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="comptable@example.com", password="Str0ngPassw0rd!23")
        _grant(user, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("500000"))
        posted = validate_invoice(invoice, user)

        assert posted.state == AccMove.STATE_POSTED
        assert posted.invoice_state == AccMove.INVOICE_STATE_VALIDATED
        assert posted.reference != ""


def test_validate_invoice_without_permission_is_refused(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="nobody@example.com", password="Str0ngPassw0rd!23")
        invoice = _make_invoice(ledger, Decimal("500000"))

        with pytest.raises(TransitionPermissionError):
            validate_invoice(invoice, user)


def test_validate_invoice_between_thresholds_requires_double_validation(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c2@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove")
        resp_commercial = User.objects.create_user(
            email="rc@example.com", password="Str0ngPassw0rd!23"
        )
        Group.objects.get_or_create(name="resp_commercial")[0].user_set.add(resp_commercial)

        invoice = _make_invoice(ledger, Decimal("5000000"))  # entre 2M et 10M

        with pytest.raises(ApprovalRequiredError):
            validate_invoice(invoice, comptable)

        first_request = ApprovalRequest.objects.get(
            object_id=str(invoice.id), rule__approver_role="comptable"
        )
        decide(first_request, comptable, approved=True)

        with pytest.raises(ApprovalRequiredError):
            validate_invoice(invoice, comptable)

        second_request = ApprovalRequest.objects.get(
            object_id=str(invoice.id), rule__approver_role="resp_commercial"
        )
        decide(second_request, resp_commercial, approved=True)

        posted = validate_invoice(invoice, comptable)
        assert posted.state == AccMove.STATE_POSTED


def test_validate_invoice_rejected_by_an_approver_raises(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c3@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("5000000"))

        with pytest.raises(ApprovalRequiredError):
            validate_invoice(invoice, comptable)

        first_request = ApprovalRequest.objects.get(
            object_id=str(invoice.id), rule__approver_role="comptable"
        )
        decide(first_request, comptable, approved=False)

        with pytest.raises(ValidationError):
            validate_invoice(invoice, comptable)


def test_cancel_draft_invoice_requires_motif_and_permission(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c4@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "cancel_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))

        with pytest.raises(ValidationError):
            cancel_invoice(invoice, comptable, motif="")

        cancelled = cancel_invoice(invoice, comptable, motif="Erreur de saisie")
        assert cancelled.invoice_state == AccMove.INVOICE_STATE_CANCELLED


def test_cancel_posted_invoice_is_refused(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c5@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove", "cancel_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))
        posted = validate_invoice(invoice, comptable)

        with pytest.raises(ValidationError):
            cancel_invoice(posted, comptable, motif="Trop tard")
