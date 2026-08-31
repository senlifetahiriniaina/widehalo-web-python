"""Compte rendu d'activite achats (§5.6.2, PU7 du sous-sequencement
`purchase` — cf. plan) : creation et workflow simple `draft -> submitted
-> validated/rejected`, meme discipline `PurRequisition` (pas de FSM
`django-fsm`, deux transitions terminales triviales, cf. docstring
`models.py::PurCra`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.purchase.models import PurCra, PurOrder


def create_cra(
    *,
    tenant: Tenant,
    date: dt.date,
    buyer: User,
    partner_id: UUID,
    activity_type: str,
    hours: Decimal,
    order: PurOrder | None = None,
    comment: str = "",
) -> PurCra:
    reference = next_reference(tenant, "PCRA", timezone.now().year)
    return PurCra.objects.create(
        tenant=tenant,
        reference=reference,
        date=date,
        buyer=buyer,
        partner_id=partner_id,
        activity_type=activity_type,
        hours=hours,
        order=order,
        comment=comment,
    )


def submit_cra(cra: PurCra) -> PurCra:
    if cra.state != PurCra.STATE_DRAFT:
        raise ValidationError(_("Seul un CRA en brouillon peut être soumis."))
    cra.state = PurCra.STATE_SUBMITTED
    cra.save(update_fields=["state"])
    return cra


def validate_cra(cra: PurCra, *, validated_by: User | None = None) -> PurCra:
    if cra.state != PurCra.STATE_SUBMITTED:
        raise ValidationError(_("Seul un CRA soumis peut être valide."))
    cra.state = PurCra.STATE_VALIDATED
    update_fields = ["state"]
    if validated_by is not None:
        cra.updated_by = validated_by
        update_fields.append("updated_by")
    cra.save(update_fields=update_fields)
    return cra


def reject_cra(cra: PurCra, *, reason: str) -> PurCra:
    if cra.state != PurCra.STATE_SUBMITTED:
        raise ValidationError(_("Seul un CRA soumis peut être rejeté."))
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour rejeter un CRA."))
    cra.state = PurCra.STATE_REJECTED
    cra.rejection_reason = reason
    cra.save(update_fields=["state", "rejection_reason"])
    return cra
