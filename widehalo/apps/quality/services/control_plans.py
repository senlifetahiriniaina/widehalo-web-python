"""Plan de controle HACCP et points critiques (Bloc D, D1). Contrairement a
`mrp.services.bom`, aucune notion de version/immutabilite ici — un plan de
controle est corrige en place, ses points critiques ajustes librement,
`config/settings/base.py::BUDGET_MAX_MODELS` n'ayant justifie qu'un
versionnage reel la ou le CDC l'exige explicitement (nomenclatures)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.db import models

from apps.core.models.tenant import Tenant
from apps.quality.models import QltControlPlan, QltCriticalPoint
from apps.quality.services.generic_ref import resolve_generic_reference


def create_control_plan(
    *,
    tenant: Tenant,
    name: str,
    frequency_days: int = 0,
    content_object: models.Model | None = None,
    notes: str = "",
) -> QltControlPlan:
    """`content_object` : document/article gouverne par ce plan (ex. un
    `catalog.ProductTemplate`), rattachement optionnel — meme choix assume
    que `core.RiskItem` (un plan generique sans document precis reste un
    cas d'usage reel)."""
    return QltControlPlan.objects.create(
        tenant=tenant,
        name=name,
        frequency_days=frequency_days,
        notes=notes,
        **resolve_generic_reference(content_object),
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
    return QltCriticalPoint.objects.create(
        tenant=control_plan.tenant,
        control_plan=control_plan,
        name=name,
        unit=unit,
        limit_min=limit_min,
        limit_max=limit_max,
        sequence=sequence,
    )


def get_last_measurement_date(
    critical_point: QltCriticalPoint, *, lot_variant_id: Any, lot_name: str
) -> dt.datetime | None:
    """Bloc D, D3 : date de la derniere mesure REELLEMENT prise pour ce
    lot sur ce point critique — utilisee par la future commande d'alerte
    QUA-9 (frequence attendue vs. dernier controle constate). Ecrite des
    D1 (fonction pure, sans effet de bord) pour eviter que D3 ne
    reintroduise une seconde requete divergente sur `QltMeasurement`."""
    measurement = (
        critical_point.measurements.filter(lot_variant_id=lot_variant_id, lot_name=lot_name)
        .order_by("-measured_at")
        .first()
    )
    return measurement.measured_at if measurement is not None else None
