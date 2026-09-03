"""Calcul et persistance des prévisions d'une série (atelier de prévision,
diagnostic de série — cahier §13.2). La sélection de modèle (FOR-3) est
faite UNE FOIS sur l'historique d'apprentissage, puis appliquée pas à pas
pour les `horizon_months` périodes futures (chaque prévision devient à son
tour une donnée d'entrée pour la suivante — pratique standard de
prévision multi-pas, jamais une ré-sélection de modèle par pas, qui
romprait la reproductibilité de FOR-3 pour un même horizon)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.forecast.models import ForSeriesForecast
from apps.forecast.services.engine import MODEL_FUNCTIONS, select_model
from apps.forecast.services.history import load_series_history

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def _next_month(period: dt.date) -> dt.date:
    return (period.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def compute_and_store_forecast(
    tenant: Tenant,
    *,
    dimension_type: str,
    dimension_value: str,
    horizon_months: int = 6,
    history_periods: int = 36,
) -> list[ForSeriesForecast]:
    history = load_series_history(
        tenant,
        dimension_type=dimension_type,
        dimension_value=dimension_value,
        periods=history_periods,
    )
    selection = select_model(history.training_periods, history.training_values)
    if selection is None:
        return []

    model_fn = MODEL_FUNCTIONS[selection.selected_model]
    working_values = [float(v) for v in history.training_values]
    working_months = [p.month for p in history.training_periods]
    last_period = (
        history.full_periods[-1] if history.full_periods else timezone.now().date().replace(day=1)
    )

    results = []
    now = timezone.now()
    for _ in range(horizon_months):
        last_period = _next_month(last_period)
        predicted = model_fn(working_values, working_months)
        working_values.append(predicted)
        working_months.append(last_period.month)

        row, _created = ForSeriesForecast.objects.update_or_create(
            tenant=tenant,
            dimension_type=dimension_type,
            dimension_value=dimension_value,
            period=last_period,
            defaults={
                "reference_naive_value": selection.reference_naive_value,
                "reference_naive_beats_selected": selection.reference_naive_beats_selected,
                "selected_model": selection.selected_model,
                "selected_model_score": selection.selected_score,
                "rejected_models": selection.rejected_models,
                "test_window_start": selection.test_window_start,
                "test_window_end": selection.test_window_end,
                "insufficient_history_for_seasonality": selection.insufficient_history_for_seasonality,
                "error_mae_pct": selection.error_mae_pct,
                "error_weighted_pct": selection.error_weighted_pct,
                "error_bias_pct": selection.error_bias_pct,
                "statistical_value": Decimal(str(round(predicted, 4))),
                "computed_at": now,
            },
        )
        results.append(row)
    return results
