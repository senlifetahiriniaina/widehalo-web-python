"""Mesures HACCP contre un point critique (Bloc D, D1, QUA-1/2/3) : une
mesure hors limites ouvre automatiquement une non-conformité ET bloque le
lot concerné (`stocks.services.public.set_quality_state`), dans la MÊME
transaction — jamais une mesure enregistrée sans que son verdict soit
immédiatement et durablement traduit en blocage physique si nécessaire."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.quality.models import QltCriticalPoint, QltMeasurement
from apps.quality.services.generic_ref import resolve_generic_reference
from apps.quality.services.non_conformity import create_non_conformity
from apps.stocks.services.public import QUALITY_STATE_QUARANTINE
from apps.stocks.services.public import set_quality_state as _set_stock_quality_state


def _is_within_limits(critical_point: QltCriticalPoint, value: Decimal) -> bool:
    below_min = critical_point.limit_min is not None and value < critical_point.limit_min
    above_max = critical_point.limit_max is not None and value > critical_point.limit_max
    return not (below_min or above_max)


@transaction.atomic
def record_measurement(
    critical_point: QltCriticalPoint,
    *,
    tenant: Tenant,
    value: Decimal,
    measured_by: User,
    lot_variant_id: Any = None,
    lot_name: str = "",
    content_object: models.Model | None = None,
    measured_at: dt.datetime | None = None,
) -> QltMeasurement:
    """`@transaction.atomic` (QUA-1/2/3) : la mesure, l'ouverture de la
    non-conformité ET le blocage du lot doivent réussir ou échouer
    ENSEMBLE — jamais une mesure hors limites enregistrée sans que le lot
    concerné soit effectivement bloqué (ou l'inverse)."""
    is_within = _is_within_limits(critical_point, value)
    measurement = QltMeasurement.objects.create(
        tenant=tenant,
        critical_point=critical_point,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        value=value,
        is_within_limits=is_within,
        measured_by=measured_by,
        measured_at=measured_at or timezone.now(),
        **resolve_generic_reference(content_object),
    )

    if not is_within:
        description = _(
            "Mesure hors limites sur « %(point)s » : %(value)s (attendu entre %(min)s et %(max)s)."
        ) % {
            "point": critical_point.name,
            "value": value,
            "min": critical_point.limit_min if critical_point.limit_min is not None else "—",
            "max": critical_point.limit_max if critical_point.limit_max is not None else "—",
        }
        create_non_conformity(
            tenant=tenant,
            opened_by=measured_by,
            description=str(description),
            lot_variant_id=lot_variant_id,
            lot_name=lot_name,
            measurement=measurement,
        )
        if lot_variant_id is not None and lot_name:
            _set_stock_quality_state(
                tenant,
                variant_id=lot_variant_id,
                lot_name=lot_name,
                state=QUALITY_STATE_QUARANTINE,
                description=str(description),
                decided_by=measured_by,
            )

    return measurement
