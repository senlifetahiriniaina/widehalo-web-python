"""Compte rendu d'incident achats (§5.6.2, PU7 du sous-sequencement
`purchase` — cf. plan) : creation et cloture d'un incident fournisseur
(retard, non conformite, litige, rupture, incident douanier), cf.
docstring `models.py::PurCri` pour la distinction avec la branche FSM
"en litige" de `PurOrder`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.purchase.models import PurCri, PurOrder


def create_cri(
    *,
    tenant: Tenant,
    date: dt.date,
    type: str,  # noqa: A002 — coherent avec `MrpCri.type`/`PurCri.type` (nom de champ CDC)
    partner_id: UUID,
    description: str,
    order: PurOrder | None = None,
    impact: str = "",
    action_taken: str = "",
    cost_mga: Decimal = Decimal(0),
    attachment_document_ids: list[UUID] | None = None,
) -> PurCri:
    reference = next_reference(tenant, "PCRI", timezone.now().year)
    return PurCri.objects.create(
        tenant=tenant,
        reference=reference,
        date=date,
        type=type,
        partner_id=partner_id,
        order=order,
        description=description,
        impact=impact,
        action_taken=action_taken,
        cost_mga=cost_mga,
        attachment_document_ids=[str(doc_id) for doc_id in (attachment_document_ids or [])],
    )


def close_cri(cri: PurCri, *, action_taken: str = "") -> PurCri:
    if cri.state == PurCri.STATE_CLOSED:
        raise ValidationError(_("Ce CRI est déjà cloture."))
    cri.state = PurCri.STATE_CLOSED
    update_fields = ["state"]
    if action_taken:
        cri.action_taken = action_taken
        update_fields.append("action_taken")
    cri.save(update_fields=update_fields)
    return cri
