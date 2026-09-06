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

from apps.forecast.models import ForSeriesForecast
from apps.forecast.services.engine import MODEL_FUNCTIONS, select_model
from apps.forecast.services.history import SeriesHistory, load_series_history
from django.utils import timezone

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
                "insufficient_history_for_seasonality": (
                    selection.insufficient_history_for_seasonality
                ),
                "error_mae_pct": selection.error_mae_pct,
                "error_weighted_pct": selection.error_weighted_pct,
                "error_bias_pct": selection.error_bias_pct,
                "statistical_value": Decimal(str(round(predicted, 4))),
                "computed_at": now,
            },
        )
        results.append(row)

    # FOR-7 (L9) : rapprocher les periodes ECHUES de leur realise.
    #
    # `measure_adjustment_contribution` etait ecrite, testee, et appelee
    # PAR SON SEUL TEST — aucun appelant de production. Consequence
    # visible : l'onglet « qualite de prevision » filtre sur
    # `statistical_error_pct__isnull=False` (`forecast/views.py:37-40`), et
    # comme rien ne renseignait jamais ce champ en exploitation, il restait
    # VIDE en permanence. Le critere « apport de l'ajustement humain
    # mesure » etait donc infaisable, pas seulement non mesure.
    #
    # Le rapprochement a lieu ICI parce que c'est le seul moment ou les
    # deux moities sont disponibles ensemble : l'historique reel
    # fraichement charge, et les previsions passees deja persistees. Un
    # traitement separe aurait recharge l'un des deux.
    _reconcile_elapsed_periods(
        tenant,
        dimension_type=dimension_type,
        dimension_value=dimension_value,
        history=history,
    )
    return results


def _reconcile_elapsed_periods(
    tenant: Tenant,
    *,
    dimension_type: str,
    dimension_value: str,
    history: SeriesHistory,
) -> int:
    """Mesure l'erreur des previsions dont la periode est desormais echue.

    Une periode est « echue » quand l'historique porte une valeur reelle
    pour elle — c'est la definition operatoire, et non « la date est
    passee » : une periode close mais dont les ventes ne sont pas encore
    consolidees donnerait une erreur calculee contre un realise partiel,
    c'est-a-dire un chiffre faux presente comme une mesure de qualite.

    Les periodes EXCLUES de l'apprentissage (`history.excluded_periods` —
    valeurs aberrantes ecartees par le diagnostic de serie) sont ignorees
    ici aussi : mesurer la qualite d'une prevision contre un realise qu'on
    a soi-meme juge non representatif ne dirait rien d'utile.

    Idempotent : recalculer une erreur deja mesuree donne la meme valeur.
    Retourne le nombre de previsions rapprochees."""
    from apps.forecast.services.adjustments import measure_adjustment_contribution

    actual_by_period = {
        period: value
        for period, value in zip(history.full_periods, history.full_values, strict=True)
        if period not in history.excluded_periods
    }
    if not actual_by_period:
        return 0

    elapsed = ForSeriesForecast.objects.filter(
        tenant=tenant,
        dimension_type=dimension_type,
        dimension_value=dimension_value,
        period__in=list(actual_by_period),
    )
    measured = 0
    for forecast in elapsed:
        measure_adjustment_contribution(forecast, actual_value=actual_by_period[forecast.period])
        measured += 1
    return measured
