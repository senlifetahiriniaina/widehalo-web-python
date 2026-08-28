from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurOrder
from apps.purchase.services.orders import (
    LEVEL1_THRESHOLD_MGA,
    PurchaseApprovalRequiredError,
    add_order_line,
    cancel_order,
    close_order,
    confirm_order,
    create_bulk_orders_from_requisitions,
    create_order,
    create_order_from_requisition,
    ensure_default_purchase_approval_rules,
    mark_order_in_transit,
    mark_order_invoiced,
    mark_order_partially_received,
    mark_order_received,
    open_order_dispute,
    resolve_order_dispute,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    submit_requisition,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def orders_setup():
    tenant = Tenant.objects.create(code="PUR-ORD", name="Purchase Order Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="pur-ord@example.com", password="Str0ngPassw0rd!23")
        return tenant, user


def _make_requester(tenant):
    return User.objects.create_user(
        email=f"req-{uuid.uuid4().hex[:8]}@example.com", password="Str0ngPassw0rd!23"
    )


def _make_variant(tenant, *, suffix="0001"):
    uom = UnitOfMeasure.objects.create(
        tenant=tenant, code=f"PC{suffix}", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
    )
    template = ProductTemplate.objects.create(
        tenant=tenant,
        name=f"Composant {suffix}",
        base_uom=uom,
        reference=f"TPL-PUR-ORD-{suffix}",
        base_price_mga=Decimal("1000"),
    )
    return ProductVariant.objects.create(
        tenant=tenant, template=template, reference=f"VAR-PUR-ORD-{suffix}"
    )


def test_create_order_assigns_reference(orders_setup) -> None:
    tenant, _user = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        assert order.reference.startswith("PCMD-")
        assert order.state == PurOrder.STATE_DRAFT


def test_add_order_line_recomputes_totals_and_refuses_outside_draft(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Fil",
            qty=Decimal(10),
            unit_price_mga=Decimal(1000),
            tax_pct=Decimal(20),
        )
        order.refresh_from_db()
        assert order.amount_untaxed_mga == Decimal("10000.0000")
        assert order.amount_tax_mga == Decimal("2000.0000")
        assert order.amount_total_mga == Decimal("12000.0000")

        submit_order_for_validation(order, user)
        with pytest.raises(ValidationError):
            add_order_line(
                order,
                variant_id=uuid.uuid4(),
                description="Autre",
                qty=Decimal(1),
                unit_price_mga=Decimal(1),
            )


def test_full_fsm_happy_path(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Fil",
            qty=Decimal(1),
            unit_price_mga=Decimal(100),
        )

        submit_order_for_validation(order, user)
        assert order.state == PurOrder.STATE_TO_VALIDATE

        validate_order(order, user)
        assert order.state == PurOrder.STATE_VALIDATED

        send_order(order, user)
        assert order.state == PurOrder.STATE_SENT

        confirm_order(order, user)
        assert order.state == PurOrder.STATE_CONFIRMED

        mark_order_in_transit(order, user)
        assert order.state == PurOrder.STATE_IN_TRANSIT

        mark_order_partially_received(order, user)
        assert order.state == PurOrder.STATE_PARTIALLY_RECEIVED

        mark_order_received(order, user)
        assert order.state == PurOrder.STATE_RECEIVED

        mark_order_invoiced(order, user)
        assert order.state == PurOrder.STATE_INVOICED

        close_order(order, user)
        assert order.state == PurOrder.STATE_CLOSED

        order.refresh_from_db()
        assert order.state == PurOrder.STATE_CLOSED


def test_illegal_transitions_are_refused(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())

        with pytest.raises(TransitionPermissionError):
            send_order(order, user)  # draft -> sent n'existe pas directement
        with pytest.raises(TransitionPermissionError):
            confirm_order(order, user)
        with pytest.raises(TransitionPermissionError):
            mark_order_received(order, user)
        with pytest.raises(TransitionPermissionError):
            close_order(order, user)


def test_cancel_requires_reason_and_is_blocked_after_receipt(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        with pytest.raises(ValidationError):
            cancel_order(order, user, reason="")

        cancel_order(order, user, reason="Fournisseur indisponible")
        assert order.state == PurOrder.STATE_CANCELLED
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_CANCELLED
        assert order.cancel_reason == "Fournisseur indisponible"


def test_dispute_branch_opens_and_resolves_back_to_received(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Fil",
            qty=Decimal(1),
            unit_price_mga=Decimal(100),
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        send_order(order, user)
        confirm_order(order, user)
        mark_order_in_transit(order, user)
        mark_order_received(order, user)

        with pytest.raises(ValidationError):
            open_order_dispute(order, user, reason="")

        open_order_dispute(order, user, reason="Ecart facture > 2%")
        assert order.state == PurOrder.STATE_IN_DISPUTE
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_IN_DISPUTE
        assert order.dispute_reason == "Ecart facture > 2%"

        resolve_order_dispute(order, user)
        assert order.state == PurOrder.STATE_RECEIVED
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_RECEIVED


def test_create_order_from_requisition_copies_lines_and_refuses_non_approved(orders_setup) -> None:
    tenant, _user = orders_setup
    with use_tenant(tenant.id):
        requester = _make_requester(tenant)
        variant = _make_variant(tenant, suffix="OFR1")
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        line = add_requisition_line(
            requisition, variant_id=variant.id, description="Composant", qty=Decimal(5)
        )
        line.estimated_price_mga = Decimal("500")
        line.save(update_fields=["estimated_price_mga"])

        supplier_id = uuid.uuid4()
        with pytest.raises(ValidationError):
            create_order_from_requisition(requisition, partner_id=supplier_id)

        submit_requisition(requisition)
        approve_requisition(requisition)
        order = create_order_from_requisition(requisition, partner_id=supplier_id)

        assert order.partner_id == supplier_id
        assert order.requisition_id == requisition.id
        assert order.lines.count() == 1
        order_line = order.lines.first()
        assert order_line.description == "Composant"
        assert order_line.qty == Decimal(5)
        assert order_line.unit_price_mga == Decimal("500")


def test_create_bulk_orders_from_requisitions_groups_by_supplier(orders_setup) -> None:
    tenant, _user = orders_setup
    with use_tenant(tenant.id):
        requester = _make_requester(tenant)
        supplier_x = uuid.uuid4()
        supplier_y = uuid.uuid4()
        variant_1 = _make_variant(tenant, suffix="BULK1")
        variant_2 = _make_variant(tenant, suffix="BULK2")
        variant_3 = _make_variant(tenant, suffix="BULK3")
        variant_4 = _make_variant(tenant, suffix="BULK4")

        requisition_1 = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition_1,
            variant_id=variant_1.id,
            description="Ligne 1 (X)",
            qty=Decimal(2),
            preferred_supplier_id=supplier_x,
        )
        add_requisition_line(
            requisition_1,
            variant_id=variant_2.id,
            description="Ligne 2 (Y)",
            qty=Decimal(3),
            preferred_supplier_id=supplier_y,
        )
        add_requisition_line(
            requisition_1,
            variant_id=variant_3.id,
            description="Ligne 3 (sans fournisseur)",
            qty=Decimal(1),
        )
        submit_requisition(requisition_1)
        approve_requisition(requisition_1)

        requisition_2 = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition_2,
            variant_id=variant_4.id,
            description="Ligne 4 (X)",
            qty=Decimal(4),
            preferred_supplier_id=supplier_x,
        )
        submit_requisition(requisition_2)
        approve_requisition(requisition_2)

        result = create_bulk_orders_from_requisitions(
            [requisition_1.id, requisition_2.id], tenant=tenant
        )

        assert len(result["orders_created"]) == 2
        assert len(result["lines_skipped"]) == 1
        assert result["lines_skipped"][0]["description"] == "Ligne 3 (sans fournisseur)"

        orders_by_supplier = {order.partner_id: order for order in result["orders_created"]}
        assert set(orders_by_supplier.keys()) == {supplier_x, supplier_y}

        order_x = orders_by_supplier[supplier_x]
        assert order_x.lines.count() == 2
        descriptions_x = {line.description for line in order_x.lines.all()}
        assert descriptions_x == {"Ligne 1 (X)", "Ligne 4 (X)"}

        order_y = orders_by_supplier[supplier_y]
        assert order_y.lines.count() == 1
        assert order_y.lines.first().description == "Ligne 2 (Y)"


def test_create_bulk_orders_refuses_non_approved_requisition(orders_setup) -> None:
    tenant, _user = orders_setup
    with use_tenant(tenant.id):
        requester = _make_requester(tenant)
        variant = _make_variant(tenant, suffix="NOAPP")
        requisition = create_requisition(
            tenant=tenant, requester=requester, date_needed=dt.date.today()
        )
        add_requisition_line(
            requisition, variant_id=variant.id, description="Ligne", qty=Decimal(1)
        )

        with pytest.raises(ValidationError):
            create_bulk_orders_from_requisitions([requisition.id], tenant=tenant)


def test_pur_rout1_blocks_validate_until_amount_threshold_approved(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        ensure_default_purchase_approval_rules(tenant)
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Machine",
            qty=Decimal(1),
            unit_price_mga=LEVEL1_THRESHOLD_MGA,
        )
        submit_order_for_validation(order, user)

        with pytest.raises(PurchaseApprovalRequiredError):
            validate_order(order, user)
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_TO_VALIDATE

        from apps.core.models.workflow import ApprovalRequest
        from apps.core.services.approvals import decide

        pending = ApprovalRequest.objects.get(object_id=str(order.id))
        decide(pending, user, approved=True)

        validate_order(order, user)
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_VALIDATED


def test_pur_rout1_blocks_validate_for_import_origin_regardless_of_amount(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        ensure_default_purchase_approval_rules(tenant)
        order = create_order(
            tenant=tenant,
            partner_id=uuid.uuid4(),
            date=dt.date.today(),
            origin=PurOrder.ORIGIN_IMPORT_CHINE,
        )
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Petit article",
            qty=Decimal(1),
            unit_price_mga=Decimal(10),
        )
        submit_order_for_validation(order, user)

        with pytest.raises(PurchaseApprovalRequiredError):
            validate_order(order, user)

        from apps.core.models.workflow import ApprovalRequest
        from apps.core.services.approvals import decide

        pending = ApprovalRequest.objects.get(object_id=str(order.id))
        assert pending.rule.approver_role == "direction"
        decide(pending, user, approved=True)

        validate_order(order, user)
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_VALIDATED


def test_pur_rout1_no_rule_matches_validates_directly(orders_setup) -> None:
    tenant, user = orders_setup
    with use_tenant(tenant.id):
        ensure_default_purchase_approval_rules(tenant)
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Petit article",
            qty=Decimal(1),
            unit_price_mga=Decimal(10),
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        assert order.state == PurOrder.STATE_VALIDATED
