"""Historique d'une série, prêt pour le moteur statistique — lit
exclusivement `apps.analytics.services.public.get_sales_value_series`
(jamais un accès direct aux faits de l'entrepôt, règle de couplage n°1) et
retire les points marqués `ForExceptionalPoint` (FOR-4 : « exclus de
l'apprentissage sans disparaître de l'historique affiché » — la fonction
ci-dessous retourne donc DEUX listes séparées, l'historique complet pour
l'affichage et l'historique d'apprentissage filtré)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.analytics.services.public import get_sales_value_series
from apps.forecast.models import ForExceptionalPoint

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


@dataclass
class SeriesHistory:
    full_periods: list[dt.date]
    full_values: list[Decimal]
    training_periods: list[dt.date]
    training_values: list[Decimal]
    excluded_periods: set[dt.date]


def load_series_history(
    tenant: Tenant, *, dimension_type: str, dimension_value: str, periods: int = 36
) -> SeriesHistory:
    raw = get_sales_value_series(
        tenant, dimension_type=dimension_type, dimension_value=dimension_value, periods=periods
    )
    excluded = set(
        ForExceptionalPoint.objects.filter(
            tenant=tenant, dimension_type=dimension_type, dimension_value=dimension_value
        ).values_list("period", flat=True)
    )
    full_periods = [row["period"] for row in raw]
    full_values = [row["value"] for row in raw]
    training_periods = [p for p in full_periods if p not in excluded]
    training_values = [v for p, v in zip(full_periods, full_values) if p not in excluded]
    return SeriesHistory(
        full_periods=full_periods,
        full_values=full_values,
        training_periods=training_periods,
        training_values=training_values,
        excluded_periods=excluded,
    )
