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

from apps.core.events import publish_event
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
        raise ValidationError(_("Un motif est obligatoire pour ouvrir une non-conformité."))
    reference = next_reference(tenant, "QLT-NC", timezone.now().year)
    non_conformity = QltNonConformity.objects.create(
        tenant=tenant,
        reference=reference,
        measurement=measurement,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        description=description,
        opened_by=opened_by,
        **resolve_generic_reference(content_object),
    )
    # L11 : publie ici et non dans les appelants, pour que les DEUX chemins
    # d'ouverture — manuel, et automatique depuis une mesure hors limites —
    # produisent le meme evenement. Publier cote appelant aurait laisse le
    # chemin automatique muet, c'est-a-dire justement celui qu'on veut
    # automatiser. `publish_event` programme la distribution APRES commit :
    # un rollback n'emet rien.
    publish_event(
        "quality.non_conformity_opened",
        {
            "non_conformity_id": str(non_conformity.id),
            "reference": non_conformity.reference,
            "lot_variant_id": str(lot_variant_id) if lot_variant_id else None,
            "lot_name": lot_name,
            "description": description,
            # Distingue le chemin automatique du chemin manuel sans que
            # l'abonne ait a interroger la base.
            "from_measurement": measurement is not None,
        },
        tenant_id=str(tenant.id),
    )
    return non_conformity


def close_non_conformity(
    non_conformity: QltNonConformity, *, closed_by: User, closing_reason: str
) -> QltNonConformity:
    if not closing_reason:
        raise ValidationError(_("Un motif est obligatoire pour clôturer une non-conformité."))
    if non_conformity.state == QltNonConformity.STATE_CLOSED:
        raise ValidationError(_("Cette non-conformité est déjà clôturée."))
    non_conformity.state = QltNonConformity.STATE_CLOSED
    non_conformity.closed_by = closed_by
    non_conformity.closed_at = timezone.now()
    non_conformity.closing_reason = closing_reason
    non_conformity.save(update_fields=["state", "closed_by", "closed_at", "closing_reason"])
    publish_event(
        "quality.non_conformity_closed",
        {
            "non_conformity_id": str(non_conformity.id),
            "reference": non_conformity.reference,
            "lot_variant_id": (
                str(non_conformity.lot_variant_id) if non_conformity.lot_variant_id else None
            ),
            "lot_name": non_conformity.lot_name,
            "closing_reason": closing_reason,
        },
        tenant_id=str(non_conformity.tenant_id),
    )
    return non_conformity


def has_open_non_conformity(*, tenant: Tenant, lot_variant_id: Any, lot_name: str) -> bool:
    return QltNonConformity.objects.filter(
        tenant=tenant,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        state=QltNonConformity.STATE_OPEN,
    ).exists()
