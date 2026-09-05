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
from apps.mrp.services.orders import (
    _record_scrap_movement,
    scrap_declaration_source_document,
)


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
    """RG-MRP-12 : declaration de rebut par intervention.

    **Le mouvement de stock est branche depuis L12-4 (PRD-6).** Cette
    docstring annoncait qu'il « sera branche […] une fois ces modules
    disponibles » — ils l'etaient depuis A2, `mrp` consommant deja
    `stocks.services.public.receive_production_output`. La promesse est
    tenue ici : la declaration produit desormais un `StkMove.TYPE_REBUT`.

    **`source_document` distinct de celui du rejet au poste**
    (`{reference}/SCRAP` contre `{reference}/WO{sequence}`, cf.
    `services.orders.scrap_source_document`). Les deux natures de rebut ne
    doivent JAMAIS se confondre : le taux de conformite au premier passage
    lit `MrpWorkOrder.qty_rejected`, jamais `MrpScrap` — melanger les deux
    dans un meme document gonflerait le denominateur du FPY avec du rebut
    qu'il n'a jamais compte.

    La charge analytique, elle, n'est toujours pas branchee : `cost_mga`
    reste une donnee declarative de cette entite. L'ecart est reel et
    reste signale, plutot que d'etre efface d'une docstring."""
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
    _record_scrap_movement(
        order,
        # Le rebut declare porte sa propre variante quand elle est connue
        # (matiere mise au rebut) ; a defaut c'est le produit de l'ordre.
        variant_id=variant_id or order.variant_id,
        qty=qty,
        date=scrap.date,
        source_document=scrap_declaration_source_document(order),
    )
    return scrap
