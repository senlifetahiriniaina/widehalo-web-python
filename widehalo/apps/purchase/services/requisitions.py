"""Demande d'achat (§5.6.2, PU1 du sous-sequencement `purchase` — cf.
plan) : creation, ajout de lignes (prix indicatif resolu via
`catalog.services.public.get_variant_price`, meme patron que
`sales.services.quotations.add_quotation_line`), et workflow simple
`draft -> submitted -> approved/rejected` (pas de FSM `django-fsm` a ce
stade, cf. docstring `models.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_price, select_preferred_supplier
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.purchase.models import PurRequisition, PurRequisitionLine, PurSubstitute
from apps.purchase.services.substitution import ensure_substitute_usable


def create_requisition(
    *,
    tenant: Tenant,
    requester: User,
    department: str = "",
    date_needed: dt.date,
    justification: str = "",
    source_document: str = "",
) -> PurRequisition:
    reference = next_reference(tenant, "PREQ", timezone.now().year)
    return PurRequisition.objects.create(
        tenant=tenant,
        reference=reference,
        requester=requester,
        department=department,
        date_needed=date_needed,
        justification=justification,
        source_document=source_document,
    )


def add_requisition_line(
    requisition: PurRequisition,
    *,
    variant_id: UUID,
    description: str,
    qty: Decimal,
    uom: str = "",
    preferred_supplier_id: UUID | None = None,
    substitute_id: UUID | None = None,
) -> PurRequisitionLine:
    """RG-PUR-1 (PU2, cf. plan) : quand l'appelant ne fournit pas
    `preferred_supplier_id` explicitement, il est resolu automatiquement
    via `catalog.services.public.select_preferred_supplier` (ordre
    priority > prix > delai) — reste `None` si aucune information
    fournisseur n'est enregistree pour le produit, jamais d'exception.

    RG-PUR-2 (PU2) : `substitute_id` optionnel enregistre le substitut
    utilise pour cette ligne (typiquement quand aucun fournisseur direct
    n'est trouve). `ensure_substitute_usable` est verifie avant
    acceptation — une substitution `degrade` non validee est refusee
    (acceptance test §5.6.7 n°2)."""
    if requisition.state != PurRequisition.STATE_DRAFT:
        raise ValidationError(
            _("Seule une demande d'achat en brouillon peut recevoir de nouvelles lignes.")
        )

    substitute = None
    if substitute_id is not None:
        substitute = PurSubstitute.objects.get(id=substitute_id)
        ensure_substitute_usable(substitute)

    if preferred_supplier_id is None:
        supplier_info = select_preferred_supplier(variant_id)
        if supplier_info is not None:
            preferred_supplier_id = supplier_info["partner_id"]

    estimated_price_mga = get_variant_price(variant_id)

    return PurRequisitionLine.objects.create(
        tenant=requisition.tenant,
        requisition=requisition,
        variant_id=variant_id,
        description=description,
        qty=qty,
        uom=uom,
        estimated_price_mga=estimated_price_mga,
        preferred_supplier_id=preferred_supplier_id,
        substitute=substitute,
    )


def submit_requisition(requisition: PurRequisition) -> PurRequisition:
    if requisition.state != PurRequisition.STATE_DRAFT:
        raise ValidationError(_("Seule une demande d'achat en brouillon peut être soumise."))
    if not requisition.lines.exists():
        raise ValidationError(_("Une demande d'achat sans ligne ne peut pas être soumise."))
    requisition.state = PurRequisition.STATE_SUBMITTED
    requisition.save(update_fields=["state"])
    return requisition


def approve_requisition(
    requisition: PurRequisition, *, approved_by: User | None = None
) -> PurRequisition:
    if requisition.state != PurRequisition.STATE_SUBMITTED:
        raise ValidationError(_("Seule une demande d'achat soumise peut être approuvée."))
    requisition.state = PurRequisition.STATE_APPROVED
    update_fields = ["state"]
    if approved_by is not None:
        requisition.updated_by = approved_by
        update_fields.append("updated_by")
    requisition.save(update_fields=update_fields)
    return requisition


def reject_requisition(requisition: PurRequisition, *, reason: str) -> PurRequisition:
    if requisition.state != PurRequisition.STATE_SUBMITTED:
        raise ValidationError(_("Seule une demande d'achat soumise peut être rejetée."))
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour rejeter une demande d'achat."))
    requisition.state = PurRequisition.STATE_REJECTED
    requisition.rejection_reason = reason
    requisition.save(update_fields=["state", "rejection_reason"])
    return requisition
