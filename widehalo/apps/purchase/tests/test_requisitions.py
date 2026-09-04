from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductSupplierInfo, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurSubstitute
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    reject_requisition,
    submit_requisition,
)
from apps.purchase.services.substitution import approve_substitute, create_substitute

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


# RG-PUR-1 : selection automatique du fournisseur (priority > prix > delai)
def test_add_requisition_line_auto_selects_preferred_supplier(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        # Priorite haute (valeur basse) mais prix/delai moins bons : doit gagner.
        best = ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("900"),
            lead_time_days=10,
            priority=1,
        )
        ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("100"),
            lead_time_days=1,
            priority=5,
        )
        ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("200"),
            lead_time_days=2,
            priority=5,
        )

        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        assert line.preferred_supplier_id == best.partner_id


def test_add_requisition_line_auto_selects_by_price_then_lead_time_on_priority_tie(
    purchase_setup,
) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        # Meme priorite : depart-age par prix puis delai.
        ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("300"),
            lead_time_days=1,
            priority=5,
        )
        cheapest = ProductSupplierInfo.objects.create(
            tenant=tenant,
            variant=variant,
            partner_id=uuid.uuid4(),
            price_mga=Decimal("100"),
            lead_time_days=9,
            priority=5,
        )

        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        assert line.preferred_supplier_id == cheapest.partner_id


def test_add_requisition_line_explicit_supplier_overrides_auto_selection(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=uuid.uuid4(), price_mga=Decimal("100")
        )
        explicit_supplier = uuid.uuid4()

        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition,
            variant_id=variant.id,
            description="Tissu coton",
            qty=Decimal(10),
            preferred_supplier_id=explicit_supplier,
        )
        assert line.preferred_supplier_id == explicit_supplier


def test_add_requisition_line_without_any_supplier_info_leaves_supplier_none(
    purchase_setup,
) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition, variant_id=variant.id, description="Tissu coton", qty=Decimal(10)
        )
        assert line.preferred_supplier_id is None


# RG-PUR-2 : substitut assigne a une ligne de demande d'achat
def test_add_requisition_line_accepts_approved_degrade_substitute(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant.id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        requester.groups.add(Group.objects.get_or_create(name="acheteur")[0])
        approve_substitute(substitute, approved_by=requester)

        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition,
            variant_id=variant.id,
            description="Tissu coton",
            qty=Decimal(10),
            substitute_id=substitute.id,
        )
        assert line.substitute_id == substitute.id


# §5.6.7 n°2 : une substitution degrade non validee est refusee, y compris
# a l'usage sur une ligne de demande d'achat.
def test_add_requisition_line_refuses_unapproved_degrade_substitute(purchase_setup) -> None:
    tenant, requester, variant = purchase_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant.id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )

        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        with pytest.raises(ValidationError):
            add_requisition_line(
                requisition,
                variant_id=variant.id,
                description="Tissu coton",
                qty=Decimal(10),
                substitute_id=substitute.id,
            )
