"""Non-conformite HACCP (Bloc D, D1, QUA-1/2/3) : ouverte automatiquement
par une mesure hors limites (`services/measurements.py`) ou manuellement,
clôturee avec motif obligatoire, et condition bloquante pour la
liberation d'un lot tant qu'elle reste ouverte."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.quality.models import QltMeasurement, QltNonConformity
from apps.quality.services.generic_ref import resolve_generic_reference


def create_non_conformity(
    *,
    tenant: Tenant,
    opened_by: User,
    description: str,
    lot_variant_id: Any = None,
    lot_name: str = "",
    measurement: QltMeasurement | None = None,
    content_object: models.Model | None = None,
) -> QltNonConformity:
    """Motif obligatoire (`description`) : jamais une chaîne vide,
    contrairement à `description`/`decided_by` optionnels sur
    `stocks.services.quality.set_quality_state` — c'est précisément le
    manque que QUA-3 demande de fermer côté `quality`."""
    if not description:
        raise ValidationError(
            _("Un motif est obligatoire pour ouvrir une non-conformité.")
        )
    reference = next_reference(tenant, "QLT-NC", timezone.now().year)
    return QltNonConformity.objects.create(
        tenant=tenant,
        reference=reference,
        measurement=measurement,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        description=description,
        opened_by=opened_by,
        **resolve_generic_reference(content_object),
    )


def close_non_conformity(
    non_conformity: QltNonConformity, *, closed_by: User, closing_reason: str
) -> QltNonConformity:
    if not closing_reason:
        raise ValidationError(
            _("Un motif est obligatoire pour clôturer une non-conformité.")
        )
    if non_conformity.state == QltNonConformity.STATE_CLOSED:
        raise ValidationError(_("Cette non-conformité est déjà clôturée."))
    non_conformity.state = QltNonConformity.STATE_CLOSED
    non_conformity.closed_by = closed_by
    non_conformity.closed_at = timezone.now()
    non_conformity.closing_reason = closing_reason
    non_conformity.save(
        update_fields=["state", "closed_by", "closed_at", "closing_reason"]
    )
    return non_conformity


def has_open_non_conformity(*, tenant: Tenant, lot_variant_id: Any, lot_name: str) -> bool:
    return QltNonConformity.objects.filter(
        tenant=tenant,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        state=QltNonConformity.STATE_OPEN,
    ).exists()
