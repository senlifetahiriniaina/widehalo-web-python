"""§5.11 reporting, REP4 : SAL-BL enregistre dans le registre partage et
archive via `apps.reporting.services.public.render_and_archive` (RPT-10).
`delivery_note_pdf` (nouveau, cf. `services/reports.py`) utilise le gabarit
partage `templates/reports/_base.html` (RPT-3)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import use_tenant
from apps.sales.services.orders import add_order_line, create_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def order_with_line():
    tenant = Tenant.objects.create(code="SAL-RPT-REG", name="Sales Reporting Reg Tenant")
    salesperson = User.objects.create_user(
        email="sal-rpt-reg@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today(), salesperson=salesperson
        )
        add_order_line(
            order, description="Article", qty=Decimal(2), unit_price=Decimal(1000), is_custom=True
        )
    return tenant, salesperson, order


def test_sal_bl_is_registered() -> None:
    report = get_registered_report("SAL-BL")
    assert report is not None
    assert report.module == "sales"
    assert report.is_legal_document
    assert report.supports_pdf()


def test_sal_bl_render_pdf_archives_once(order_with_line) -> None:
    tenant, salesperson, order = order_with_line
    report = get_registered_report("SAL-BL")
    assert report is not None and report.render_pdf is not None

    with use_tenant(tenant.id):
        first = report.render_pdf({"object_id": str(order.id)}, salesperson)
        second = report.render_pdf({"object_id": str(order.id)}, salesperson)
        assert first == second
        assert first.startswith(b"%PDF")
        assert Document.objects.filter(object_id=str(order.id)).count() == 1
