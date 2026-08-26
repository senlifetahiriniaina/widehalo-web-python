"""CRI (RG-MRP-10) et rebuts (RG-MRP-12)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.mrp.models import MrpCri, MrpOrder, MrpScrap, MrpWorkcenter


def create_cri(
    *,
    tenant: Tenant,
    type: str,
    workcenter: MrpWorkcenter,
    date: dt.date,
    order: MrpOrder | None = None,
    intervenant_user: User | None = None,
    intervenant_partner_id: UUID | None = None,
    duration_min: int = 0,
    description: str = "",
    cause: str = "",
    action_taken: str = "",
    cost_mga: Decimal = Decimal(0),
    downtime_min: int = 0,
    pattern_id: UUID | None = None,
) -> MrpCri:
    reference = next_reference(tenant, "MRP-CRI", timezone.now().year)
    return MrpCri.objects.create(
        tenant=tenant,
        reference=reference,
        type=type,
        workcenter=workcenter,
        order=order,
        date=date,
        intervenant_user=intervenant_user,
        intervenant_partner_id=intervenant_partner_id,
        duration_min=duration_min,
        description=description,
        cause=cause,
        action_taken=action_taken,
        cost_mga=cost_mga,
        downtime_min=downtime_min,
        pattern_id=pattern_id,
    )


def close_cri(cri: MrpCri) -> MrpCri:
    cri.state = MrpCri.STATE_CLOSED
    cri.save(update_fields=["state"])
    return cri


def declare_scrap(
    order: MrpOrder,
    *,
    declared_by: User,
    qty: Decimal,
    reason: str,
    variant_id: UUID | None = None,
    cost_mga: Decimal = Decimal(0),
) -> MrpScrap:
    """RG-MRP-12 : le mouvement de stock vers l'emplacement « rebut » et la
    charge analytique seront branches via `stocks`/`accounting.services.public`
    une fois ces modules disponibles pour ce mouvement precis — cette entite
    trace deja la declaration cote production."""
    scrap = MrpScrap.objects.create(
        tenant=order.tenant,
        order=order,
        variant_id=variant_id,
        qty=qty,
        reason=reason,
        cost_mga=cost_mga,
        date=timezone.now().date(),
        declared_by=declared_by,
    )
    order.qty_scrapped = order.qty_scrapped + qty
    order.save(update_fields=["qty_scrapped"])
    return scrap
