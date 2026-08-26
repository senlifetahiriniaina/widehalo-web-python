"""Ordres de fabrication et ordres de travail (§5.3.4, RG-MRP-7/8) :
workflow complet reutilisant `django-fsm-2`/`attempt_transition()` du
socle (meme patron que `AccMove.invoice_state`), multi-ateliers et
sous-traitance."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.mrp.models import (
    MrpBom,
    MrpOperation,
    MrpOrder,
    MrpOrderComponent,
    MrpRoutingStep,
    MrpSubcontractOrder,
    MrpWorkcenter,
    MrpWorkOrder,
    MrpWorkshop,
)
from apps.mrp.services.bom import explode


def create_order(
    *,
    tenant: Tenant,
    bom: MrpBom,
    workshop: MrpWorkshop,
    qty: Decimal,
    variant_id: UUID | None = None,
    uom_code: str = "",
    priority: str = MrpOrder.PRIORITY_NORMAL,
) -> MrpOrder:
    reference = next_reference(tenant, "MRP-OF", timezone.now().year)
    return MrpOrder.objects.create(
        tenant=tenant,
        reference=reference,
        bom=bom,
        routing=bom.routing,
        workshop=workshop,
        variant_id=variant_id,
        qty=qty,
        uom_code=uom_code or bom.uom_code,
        priority=priority,
    )


def confirm_order(order: MrpOrder, user: User) -> MrpOrder:
    """Confirme l'ordre puis materialise les composants planifies
    (RG-MRP-2/3/4) via l'eclatement de la nomenclature."""
    attempt_transition(order, "confirm", user)

    for row in explode(order.bom, order.qty):
        MrpOrderComponent.objects.create(
            tenant=order.tenant,
            order=order,
            bom_line_id=row["bom_line_id"],
            variant_id=row["component_variant_id"],
            qty_planned=row["qty"],
            uom_code=row["uom_code"],
        )
    return order


def reserve_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "reserve", user)
    for component in order.components.all():
        component.state = "reserved"
        component.save(update_fields=["state"])
    return order


def start_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "start", user)
    order.date_start = timezone.now()
    order.save(update_fields=["date_start"])
    return order


def suspend_order(order: MrpOrder, user: User, *, reason: str) -> MrpOrder:
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour suspendre un ordre de fabrication."))
    attempt_transition(order, "suspend", user, comment=reason)
    order.suspend_reason = reason
    order.save(update_fields=["suspend_reason"])
    return order


def resume_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "resume", user)
    return order


def send_to_quality_control(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "send_to_quality_control", user)
    return order


def finish_order(
    order: MrpOrder, user: User, *, qty_produced: Decimal, qty_scrapped: Decimal = Decimal(0)
) -> MrpOrder:
    attempt_transition(order, "finish", user)
    order.qty_produced = qty_produced
    order.qty_scrapped = qty_scrapped
    order.date_end = timezone.now()
    order.save(update_fields=["qty_produced", "qty_scrapped", "date_end"])
    return order


def close_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "close", user)
    return order


def cancel_order(order: MrpOrder, user: User, *, reason: str) -> MrpOrder:
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler un ordre de fabrication."))
    attempt_transition(order, "cancel", user, comment=reason)
    order.cancel_reason = reason
    order.save(update_fields=["cancel_reason"])
    return order


def create_work_order(
    order: MrpOrder,
    *,
    workcenter: MrpWorkcenter,
    qty_planned: Decimal,
    sequence: int = 0,
    routing_step: MrpRoutingStep | None = None,
    duration_planned_min: int = 0,
) -> MrpWorkOrder:
    return MrpWorkOrder.objects.create(
        tenant=order.tenant,
        order=order,
        routing_step=routing_step,
        workcenter=workcenter,
        sequence=sequence,
        qty_planned=qty_planned,
        duration_planned_min=duration_planned_min,
    )


def start_work_order(work_order: MrpWorkOrder, *, operator: User | None = None) -> MrpWorkOrder:
    work_order.state = MrpWorkOrder.STATE_IN_PROGRESS
    work_order.date_start = timezone.now()
    work_order.operator = operator
    work_order.save(update_fields=["state", "date_start", "operator"])
    return work_order


def pause_work_order(work_order: MrpWorkOrder) -> MrpWorkOrder:
    work_order.state = MrpWorkOrder.STATE_PAUSED
    work_order.save(update_fields=["state"])
    return work_order


def done_work_order(
    work_order: MrpWorkOrder, *, qty_done: Decimal, qty_rejected: Decimal = Decimal(0)
) -> MrpWorkOrder:
    now = timezone.now()
    duration_real_min = 0
    if work_order.date_start is not None:
        duration_real_min = int((now - work_order.date_start).total_seconds() // 60)

    work_order.state = MrpWorkOrder.STATE_DONE
    work_order.qty_done = qty_done
    work_order.qty_rejected = qty_rejected
    work_order.date_end = now
    work_order.duration_real_min = duration_real_min
    work_order.save(
        update_fields=["state", "qty_done", "qty_rejected", "date_end", "duration_real_min"]
    )
    return work_order


def send_to_subcontractor(
    order: MrpOrder,
    *,
    partner_id: UUID,
    qty: Decimal,
    price_unit: Decimal = Decimal(0),
    operation: MrpOperation | None = None,
) -> MrpSubcontractOrder:
    """RG-MRP-8 : trace l'envoi de matiere a un sous-traitant. Le mouvement
    de stock vers l'emplacement virtuel « chez le sous-traitant » sera
    branche via `stocks.services.public` une fois ce module construit."""
    return MrpSubcontractOrder.objects.create(
        tenant=order.tenant,
        order=order,
        partner_id=partner_id,
        operation=operation,
        qty=qty,
        price_unit=price_unit,
        date_sent=timezone.now().date(),
    )


def receive_from_subcontractor(
    subcontract_order: MrpSubcontractOrder,
    *,
    qty_received: Decimal,
    qty_rejected: Decimal = Decimal(0),
) -> MrpSubcontractOrder:
    subcontract_order.state = MrpSubcontractOrder.STATE_RECEIVED
    subcontract_order.qty_received = qty_received
    subcontract_order.qty_rejected = qty_rejected
    subcontract_order.date_received = timezone.now().date()
    subcontract_order.save(update_fields=["state", "qty_received", "qty_rejected", "date_received"])
    return subcontract_order
