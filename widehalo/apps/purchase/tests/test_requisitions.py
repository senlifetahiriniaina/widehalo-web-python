from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    reject_requisition,
    submit_requisition,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def purchase_setup():
    tenant = Tenant.objects.create(code="PUR-T", name="Purchase Tenant")
    with use_tenant(tenant.id):
        requester = User.objects.create_user(
            email="acheteur@example.com", password="Str0ngPassw0rd!23"
        )
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Tissu coton",
            base_uom=uom,
            reference="TPL-PUR-0001",
            base_price_mga=Decimal("5000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-0001"
        )
        return tenant, requester, variant


def test_create_requisition_generates_sequenced_reference(purchase_setup) -> None:
    tenant, requester, _variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        assert requisition.reference.startswith("PREQ-")
        assert requisition.state == requisition.STATE_DRAFT


def test_add_requisition_line_resolves_price_from_catalog(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        assert line.estimated_price_mga == Decimal("5000")


def test_add_requisition_line_refuses_after_submit(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        submit_requisition(requisition)

        with pytest.raises(ValidationError):
            add_requisition_line(
                requisition, variant_id=variant.id, description="Autre ligne", qty=Decimal(5)
            )


def test_submit_requisition_refuses_without_lines(purchase_setup) -> None:
    tenant, requester, _variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        with pytest.raises(ValidationError):
            submit_requisition(requisition)


def test_submit_requisition_refuses_when_not_draft(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        submit_requisition(requisition)
        with pytest.raises(ValidationError):
            submit_requisition(requisition)


def test_approve_requisition_workflow(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        submit_requisition(requisition)
        approve_requisition(requisition, approved_by=requester)
        assert requisition.state == requisition.STATE_APPROVED


def test_approve_requisition_refuses_when_not_submitted(purchase_setup) -> None:
    tenant, requester, _variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        with pytest.raises(ValidationError):
            approve_requisition(requisition)


def test_reject_requisition_requires_reason(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        submit_requisition(requisition)
        with pytest.raises(ValidationError):
            reject_requisition(requisition, reason="")


def test_reject_requisition_workflow(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        submit_requisition(requisition)
        reject_requisition(requisition, reason="Budget insuffisant")
        assert requisition.state == requisition.STATE_REJECTED
        assert requisition.rejection_reason == "Budget insuffisant"


def test_reject_requisition_refuses_when_not_submitted(purchase_setup) -> None:
    tenant, requester, _variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        with pytest.raises(ValidationError):
            reject_requisition(requisition, reason="Motif")
