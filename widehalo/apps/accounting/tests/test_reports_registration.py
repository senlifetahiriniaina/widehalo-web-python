"""§5.11 reporting, REP4 : ACC-FAC enregistre dans le registre partage et
archive via `apps.reporting.services.public.render_and_archive` (RPT-10).
Reutilise le meme montage que `test_reports.py::ledger`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.invoices import (
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def posted_invoice():
    tenant = Tenant.objects.create(code="ACC-RPT-REG", name="Accounting Reporting Reg Tenant")
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
        comptable = User.objects.create_user(
            email="rpt-reg@example.com", password="Str0ngPassw0rd!23"
        )
        from django.contrib.auth.models import Group, Permission

        group, _ = Group.objects.get_or_create(name="comptable")
        group.permissions.add(
            Permission.objects.get(
                codename="validate_accmove", content_type__app_label="accounting"
            )
        )
        comptable.groups.add(group)
        ensure_default_approval_thresholds(tenant)
        invoice = create_invoice(
            tenant=tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 15),
            partner_id=None,
            receivable_account=receivable,
            income_lines=[{"account": income, "amount": Decimal("1000"), "label": "Vente"}],
        )
        posted = validate_invoice(invoice, comptable)
        return tenant, comptable, posted


def test_acc_fac_is_registered() -> None:
    report = get_registered_report("ACC-FAC")
    assert report is not None
    assert report.module == "accounting"
    assert report.is_legal_document
    assert report.supports_pdf()


def test_acc_fac_render_pdf_archives_once(posted_invoice) -> None:
    tenant, comptable, invoice = posted_invoice
    report = get_registered_report("ACC-FAC")
    assert report is not None and report.render_pdf is not None

    with use_tenant(tenant.id):
        first = report.render_pdf({"object_id": str(invoice.id)}, comptable)
        second = report.render_pdf({"object_id": str(invoice.id)}, comptable)
        assert first == second
        assert first.startswith(b"%PDF")
        assert Document.objects.filter(object_id=str(invoice.id)).count() == 1
