"""Contrat public de l'app `quality` — seule surface qu'une autre app
metier aurait le droit d'importer (cf. tests/architecture/test_module_
boundaries.py).

Bloc D, D1 (QUA-1/2/3) : premiere consommation cross-app reelle —
`record_measurement` (ouvre une non-conformite et bloque le lot concerne
si la mesure est hors limites), `release_lot_hold` (refuse de liberer un
lot tant qu'une non-conformite liee reste ouverte). `apps.purchase`/
`apps.mrp` pourront appeler ces fonctions des D2/D4 pour rattacher un
controle a une reception/un ordre de fabrication reels."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.quality.models import QltControlPlan, QltCriticalPoint, QltMeasurement, QltNonConformity
from apps.quality.services.control_plans import add_critical_point as _add_critical_point
from apps.quality.services.control_plans import create_control_plan as _create_control_plan
from apps.quality.services.control_plans import (
    get_last_measurement_date as _get_last_measurement_date,
)
from apps.quality.services.measurements import record_measurement as _record_measurement
from apps.quality.services.non_conformity import close_non_conformity as _close_non_conformity
from apps.quality.services.non_conformity import (
    create_non_conformity as _create_non_conformity,
)
from apps.quality.services.non_conformity import (
    has_open_non_conformity as _has_open_non_conformity,
)
from apps.stocks.services.public import QUALITY_STATE_CONFORME
from apps.stocks.services.public import set_quality_state as _set_stock_quality_state


def create_control_plan(
    *,
    tenant: Tenant,
    name: str,
    frequency_days: int = 0,
    content_object: models.Model | None = None,
    notes: str = "",
) -> QltControlPlan:
    return _create_control_plan(
        tenant=tenant,
        name=name,
        frequency_days=frequency_days,
        content_object=content_object,
        notes=notes,
    )


def add_critical_point(
    control_plan: QltControlPlan,
    *,
    name: str,
    unit: str = "",
    limit_min: Decimal | None = None,
    limit_max: Decimal | None = None,
    sequence: int = 0,
) -> QltCriticalPoint:
    return _add_critical_point(
        control_plan,
        name=name,
        unit=unit,
        limit_min=limit_min,
        limit_max=limit_max,
        sequence=sequence,
    )


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
    """QUA-1/2/3 : enregistre une mesure contre un point critique. Si
    `value` est hors des limites du point critique, ouvre automatiquement
    une `QltNonConformity` ET bloque le lot `(lot_variant_id, lot_name)`
    via `stocks.services.public.set_quality_state` — même transaction,
    cf. docstring de `services/measurements.py::record_measurement`."""
    return _record_measurement(
        critical_point,
        tenant=tenant,
        value=value,
        measured_by=measured_by,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        content_object=content_object,
        measured_at=measured_at,
    )


def create_non_conformity(
    *,
    tenant: Tenant,
    opened_by: User,
    description: str,
    lot_variant_id: Any = None,
    lot_name: str = "",
    content_object: models.Model | None = None,
) -> QltNonConformity:
    """Ouverture MANUELLE d'une non-conformité (pas déclenchée par une
    mesure) — même garde motif-obligatoire que le chemin automatique de
    `record_measurement`."""
    return _create_non_conformity(
        tenant=tenant,
        opened_by=opened_by,
        description=description,
        lot_variant_id=lot_variant_id,
        lot_name=lot_name,
        content_object=content_object,
    )


def close_non_conformity(
    non_conformity: QltNonConformity, *, closed_by: User, closing_reason: str
) -> QltNonConformity:
    return _close_non_conformity(non_conformity, closed_by=closed_by, closing_reason=closing_reason)


def release_lot_hold(
    *, tenant: Tenant, lot_variant_id: Any, lot_name: str, released_by: User, reason: str
) -> UUID | None:
    """QUA-1/2/3 : refuse (`ValidationError`) de libérer un lot tant
    qu'une `QltNonConformity` `state=STATE_OPEN` existe pour
    `(lot_variant_id, lot_name)`. Motif obligatoire dans tous les cas
    (même hors non-conformité, même discipline que le reste du dépôt pour
    toute action de déblocage — ex. `cancel_order(..., reason=...)`)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour libérer un lot."))
    if _has_open_non_conformity(tenant=tenant, lot_variant_id=lot_variant_id, lot_name=lot_name):
        raise ValidationError(
            _(
                "Impossible de libérer ce lot : une non-conformité liée reste "
                "ouverte."
            )
        )
    return _set_stock_quality_state(
        tenant,
        variant_id=lot_variant_id,
        lot_name=lot_name,
        state=QUALITY_STATE_CONFORME,
        description=reason,
        decided_by=released_by,
    )


def get_last_measurement_date(
    critical_point: QltCriticalPoint, *, lot_variant_id: Any, lot_name: str
) -> dt.datetime | None:
    return _get_last_measurement_date(
        critical_point, lot_variant_id=lot_variant_id, lot_name=lot_name
    )
