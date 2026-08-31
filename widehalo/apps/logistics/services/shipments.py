"""LOG4 : expeditions — cycle de vie complet (`LogShipment`/`LogShipmentLeg`)
et LOG-REFACT1 (refacturation du fret au client, reutilise le gap deja
existant `accounting.services.public.create_customer_invoice_from_source`,
aucune nouvelle brique comptable)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_customer_invoice_from_source
from apps.core.services.workflow import attempt_transition
from apps.logistics.models import LogServiceProvider, LogShipment, LogShipmentLeg

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def create_shipment(
    tenant: Tenant,
    *,
    origin: str,
    destination: str,
    carrier: LogServiceProvider | None = None,
    incoterm: str = "",
    purchase_order_ids: list[Any] | None = None,
    sales_order_ids: list[Any] | None = None,
) -> LogShipment:
    shipment = LogShipment(
        tenant=tenant,
        origin=origin,
        destination=destination,
        carrier=carrier,
        incoterm=incoterm,
        purchase_order_ids=[str(pid) for pid in (purchase_order_ids or [])],
        sales_order_ids=[str(sid) for sid in (sales_order_ids or [])],
    )
    shipment.full_clean()
    shipment.save()
    return shipment


def add_shipment_leg(
    shipment: LogShipment,
    *,
    mode: str,
    origin: str,
    destination: str,
    carrier: LogServiceProvider | None = None,
    departure_date: dt.date | None = None,
    arrival_date: dt.date | None = None,
) -> LogShipmentLeg:
    next_sequence = (shipment.legs.count()) + 1
    leg = LogShipmentLeg(
        tenant=shipment.tenant,
        shipment=shipment,
        sequence=next_sequence,
        mode=mode,
        origin=origin,
        destination=destination,
        carrier=carrier,
        departure_date=departure_date,
        arrival_date=arrival_date,
    )
    leg.full_clean()
    leg.save()
    return leg


def book_shipment(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "book", user)
    shipment.save(update_fields=["state"])
    return shipment


def pick_up_shipment(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "pick_up", user)
    shipment.save(update_fields=["state"])
    return shipment


def mark_shipment_in_transit(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "mark_in_transit", user)
    shipment.save(update_fields=["state"])
    return shipment


def mark_shipment_arrived_at_port(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "mark_arrived_at_port", user)
    shipment.save(update_fields=["state"])
    return shipment


def start_shipment_customs_clearance(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "start_customs_clearance", user)
    shipment.save(update_fields=["state"])
    return shipment


def mark_shipment_customs_cleared(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "mark_customs_cleared", user)
    shipment.save(update_fields=["state"])
    return shipment


def deliver_shipment(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "deliver", user)
    shipment.save(update_fields=["state"])
    return shipment


def close_shipment(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "close", user)
    shipment.save(update_fields=["state"])
    return shipment


def block_shipment(shipment: LogShipment, user: User, *, reason: str) -> LogShipment:
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour bloquer une expédition."))
    attempt_transition(shipment, "block", user, comment=reason)
    shipment.block_reason = reason
    shipment.save(update_fields=["state", "block_reason"])

    from apps.core.events import publish_event

    publish_event(
        "logistics.shipment_blocked",
        {
            "shipment_id": str(shipment.id),
            "reference": shipment.reference,
            "reason": reason,
        },
        tenant_id=str(shipment.tenant_id),
    )
    return shipment


def unblock_shipment(shipment: LogShipment, user: User) -> LogShipment:
    attempt_transition(shipment, "unblock", user)
    shipment.save(update_fields=["state"])
    return shipment


def refactor_freight_to_customer(
    shipment: LogShipment,
    *,
    partner_id: UUID,
    amount_mga: Decimal | None = None,
    date: dt.date | None = None,
) -> UUID | None:
    """LOG-REFACT1 : refacture le fret au client sous forme de facture
    client reelle (`AccMove`, en `draft`, jamais auto-validee — meme
    discipline que tout le reste du module `accounting`). `amount_mga` est
    optionnel : par defaut le montant reel paye au transporteur
    (`freight_cost_mga`), mais peut etre force a un montant forfaitaire
    different (`shipment.freight_billed_to_customer_mga`, enregistre pour
    tracabilite avant l'appel comptable).

    Retourne `None`, jamais une exception, si la configuration comptable
    du tenant est incomplete (meme discipline que
    `create_customer_invoice_from_source` lui-meme)."""
    billed_amount = amount_mga if amount_mga is not None else shipment.freight_cost_mga
    shipment.freight_billed_to_customer_mga = billed_amount
    shipment.save(update_fields=["freight_billed_to_customer_mga"])

    return create_customer_invoice_from_source(
        tenant=shipment.tenant,
        partner_id=partner_id,
        date=date or dt.date.today(),
        income_lines=[
            {
                "account_id": None,
                "amount": billed_amount,
                "label": f"Refacturation fret — {shipment.reference or shipment.id}",
            }
        ],
    )
