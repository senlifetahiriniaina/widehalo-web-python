from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.sales.services.quotations import (
    accept_quotation,
    add_quotation_line,
    create_quotation,
    decline_quotation,
    expire_quotation,
    send_quotation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sales_setup():
    tenant = Tenant.objects.create(code="SALES-T", name="Sales Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="T-Shirt",
            base_uom=uom,
            reference="TPL-SAL-0001",
            base_price_mga=Decimal("15000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-SAL-0001"
        )
        return tenant, variant


def test_create_quotation_generates_sequenced_reference(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        assert quotation.reference.startswith("DEVIS-")
        assert quotation.state == quotation.STATE_DRAFT
        assert quotation.currency == "MGA"


def test_add_quotation_line_resolves_price_from_catalog(sales_setup) -> None:
    tenant, variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        line = add_quotation_line(
            quotation, variant_id=variant.id, description="T-Shirt", qty=Decimal(10)
        )
        assert line.unit_price == Decimal("15000")
        assert line.subtotal == Decimal("150000.0000")


def test_add_quotation_line_with_discount_computes_subtotal(sales_setup) -> None:
    tenant, variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        line = add_quotation_line(
            quotation,
            variant_id=variant.id,
            description="T-Shirt",
            qty=Decimal(10),
            discount_pct=Decimal(10),
        )
        assert line.subtotal == Decimal("135000.0000")  # 10*15000*0.9


def test_custom_line_does_not_require_a_variant(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        line = add_quotation_line(
            quotation,
            description="Broderie sur mesure",
            qty=Decimal(1),
            unit_price=Decimal("50000"),
            is_custom=True,
        )
        assert line.variant_id is None
        assert line.is_custom is True
        assert line.subtotal == Decimal("50000.0000")


def test_quotation_totals_recompute_after_adding_lines(sales_setup) -> None:
    tenant, variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_quotation_line(quotation, variant_id=variant.id, description="T-Shirt", qty=Decimal(2))
        add_quotation_line(
            quotation, description="Extra", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        quotation.refresh_from_db()
        assert quotation.amount_untaxed == Decimal("31000.0000")
        assert quotation.amount_total == Decimal("31000.0000")
        assert quotation.amount_total_mga == Decimal("31000.0000")


def test_quotation_state_transitions_happy_path(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        send_quotation(quotation)
        assert quotation.state == quotation.STATE_SENT

        accept_quotation(quotation)
        assert quotation.state == quotation.STATE_ACCEPTED


def test_quotation_decline_stores_reason(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        send_quotation(quotation)
        decline_quotation(quotation, reason="Prix trop eleve")
        assert quotation.state == quotation.STATE_DECLINED
        assert "Prix trop eleve" in quotation.internal_notes


def test_quotation_expire_from_sent(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        send_quotation(quotation)
        expire_quotation(quotation)
        assert quotation.state == quotation.STATE_EXPIRED


def test_send_quotation_rejects_non_draft(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        send_quotation(quotation)
        with pytest.raises(ValidationError):
            send_quotation(quotation)


def test_accept_quotation_rejects_draft(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        with pytest.raises(ValidationError):
            accept_quotation(quotation)


def test_decline_quotation_rejects_accepted(sales_setup) -> None:
    tenant, _variant = sales_setup
    with use_tenant(tenant.id):
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        send_quotation(quotation)
        accept_quotation(quotation)
        with pytest.raises(ValidationError):
            decline_quotation(quotation)
