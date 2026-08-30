"""INT3 (chantier interactivite native inter-modules) : cablage reel du
registre de risques generique (`core.services.risk.create_risk_item`) sur
l'ouverture d'un litige fournisseur, et de l'inspection qualite generique
(`core.services.quality.create_inspection`) sur une reception."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models.quality import RESULT_CONFORME, RESULT_NONCONFORME
from apps.core.models.risk import CATEGORY_SUPPLIER, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.quality import QltInspection, create_checklist_template
from apps.core.tests.utils import use_tenant
from apps.purchase.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    mark_order_in_transit,
    open_order_dispute,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.receiving import inspect_receipt, receive_order_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def int3_setup():
    tenant = Tenant.objects.create(code="PUR-INT3", name="Purchase INT3 Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="pur-int3@example.com", password="Str0ngPassw0rd!23")
        return tenant, user


def _order_confirmed(tenant, user):
    order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
    add_order_line(
        order,
        variant_id=uuid.uuid4(),
        description="Fil",
        qty=Decimal(10),
        unit_price_mga=Decimal(100),
    )
    submit_order_for_validation(order, user)
    validate_order(order, user)
    send_order(order, user)
    confirm_order(order, user)
    return order


def test_open_order_dispute_creates_risk_item(int3_setup) -> None:
    tenant, user = int3_setup
    with use_tenant(tenant.id):
        order = _order_confirmed(tenant, user)
        open_order_dispute(order, user, reason="Ecart facture > 2%")

        risk_item = RiskItem.objects.get(tenant=tenant)
        assert risk_item.category == CATEGORY_SUPPLIER
        assert risk_item.content_object == order
        assert risk_item.owner_id == user.id
        assert risk_item.score == 16


def test_confirming_order_does_not_create_risk_item(int3_setup) -> None:
    """Cas normal (pas de litige) : AUCUN `RiskItem` ne doit etre cree."""
    tenant, user = int3_setup
    with use_tenant(tenant.id):
        _order_confirmed(tenant, user)
        assert RiskItem.objects.filter(tenant=tenant).count() == 0


def test_inspect_receipt_creates_qlt_inspection(int3_setup) -> None:
    tenant, user = int3_setup
    with use_tenant(tenant.id):
        order = _order_confirmed(tenant, user)
        mark_order_in_transit(order, user)
        line = order.lines.get()
        receipt_line = receive_order_line(
            line,
            qty_received_now=Decimal(10),
            quality_status="conforme",
            user=user,
        )
        template = create_checklist_template(
            tenant=tenant,
            name="Reception - controle standard",
            items=[{"code": "EMBALLAGE", "label": "Emballage intact"}],
        )

        inspection = inspect_receipt(
            receipt_line,
            template=template,
            inspector=user,
            results=[{"code": "EMBALLAGE", "status": RESULT_CONFORME}],
            inspected_at=timezone.now(),
        )

        assert inspection.content_object == receipt_line
        assert inspection.template_id == template.id
        assert inspection.passed is True
        assert QltInspection.objects.filter(tenant=tenant).count() == 1


def test_receiving_without_explicit_inspection_creates_no_qlt_inspection(int3_setup) -> None:
    """Cas normal : `receive_order_line` seul (sans appel explicite a
    `inspect_receipt`) ne doit jamais creer d'inspection qualite generique
    automatiquement — pas de faux positif."""
    tenant, user = int3_setup
    with use_tenant(tenant.id):
        order = _order_confirmed(tenant, user)
        mark_order_in_transit(order, user)
        line = order.lines.get()
        receive_order_line(
            line,
            qty_received_now=Decimal(10),
            quality_status="conforme",
            user=user,
        )
        assert QltInspection.objects.filter(tenant=tenant).count() == 0


def test_inspect_receipt_failing_criterion_marks_not_passed(int3_setup) -> None:
    tenant, user = int3_setup
    with use_tenant(tenant.id):
        order = _order_confirmed(tenant, user)
        mark_order_in_transit(order, user)
        line = order.lines.get()
        receipt_line = receive_order_line(
            line,
            qty_received_now=Decimal(10),
            quality_status="sous_reserve",
            user=user,
        )
        template = create_checklist_template(
            tenant=tenant,
            name="Reception - controle standard 2",
            items=[{"code": "EMBALLAGE", "label": "Emballage intact"}],
        )

        inspection = inspect_receipt(
            receipt_line,
            template=template,
            inspector=user,
            results=[{"code": "EMBALLAGE", "status": RESULT_NONCONFORME}],
            inspected_at=timezone.now(),
        )

        assert inspection.passed is False
