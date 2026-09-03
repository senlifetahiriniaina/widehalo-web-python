"""Moteur statistique (`services/engine.py`) — cahier Phase 2 §13.2,
FOR-1/FOR-2/FOR-3."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from apps.forecast.services.engine import (
    MIN_HISTORY_FOR_SEASONALITY,
    backtest,
    double_exponential_smoothing,
    moving_average,
    naive_seasonal,
    select_model,
    simple_exponential_smoothing,
)


def _monthly_periods(n: int, start=(2023, 1)) -> list[dt.date]:
    periods = []
    year, month = start
    for _ in range(n):
        periods.append(dt.date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def test_naive_seasonal_uses_value_from_one_year_ago() -> None:
    history = [float(i) for i in range(1, 25)]  # 24 mois, valeurs 1..24
    assert naive_seasonal(history) == history[-12]


def test_naive_seasonal_falls_back_to_last_value_when_history_short() -> None:
    history = [10.0, 20.0, 30.0]
    assert naive_seasonal(history) == 30.0


def test_moving_average_averages_the_window() -> None:
    assert moving_average([10.0, 20.0, 30.0], window=3) == 20.0


def test_simple_exponential_smoothing_stays_between_min_and_max_of_flat_series() -> None:
    history = [100.0] * 10
    assert simple_exponential_smoothing(history) == 100.0


def test_double_exponential_smoothing_projects_a_trend() -> None:
    # Serie parfaitement lineaire +10/mois : le lissage double doit
    # capturer la tendance et projeter une valeur proche de 110.
    history = [float(10 * i) for i in range(1, 11)]  # 10..100
    forecast = double_exponential_smoothing(history, alpha=0.8, beta=0.8)
    assert 95.0 < forecast < 125.0


def test_backtest_returns_none_when_history_too_short() -> None:
    result = backtest([10.0], [1], "moyenne_mobile", test_periods=6)
    assert result is None


def test_backtest_computes_mae_and_bias_on_perfect_flat_series() -> None:
    history = [100.0] * 20
    months = [((i % 12) + 1) for i in range(20)]
    result = backtest(history, months, "moyenne_mobile", test_periods=6)
    assert result is not None
    assert result.mae_pct == 0.0
    assert result.bias_pct == 0.0


def test_select_model_flags_insufficient_history_for_seasonality() -> None:
    periods = _monthly_periods(10)
    values = [Decimal(100) for _ in periods]

    selection = select_model(periods, values)

    assert selection is not None
    assert selection.insufficient_history_for_seasonality is True
    assert len(periods) < MIN_HISTORY_FOR_SEASONALITY


def test_select_model_never_selects_a_seasonal_model_with_insufficient_history() -> None:
    # H10 : historique < 2 cycles annuels complets -> "naive_saisonnier"/
    # "lissage_triple" jamais retenus comme modele SELECTIONNE, meme si la
    # reference naive elle-meme reste toujours calculee/affichee (FOR-1).
    periods = _monthly_periods(18)
    values = [Decimal(100 + (i % 7) * 15) for i in range(18)]

    selection = select_model(periods, values)

    assert selection is not None
    assert selection.insufficient_history_for_seasonality is True
    assert selection.selected_model not in ("naive_saisonnier", "lissage_triple")
    assert selection.reference_naive_value is not None


def test_select_model_is_reproducible_for_the_same_history() -> None:
    periods = _monthly_periods(30)
    values = [Decimal(100 + (i % 5) * 10) for i in range(30)]

    first = select_model(periods, values)
    second = select_model(periods, values)

    assert first is not None and second is not None
    assert first.selected_model == second.selected_model
    assert first.selected_score == second.selected_score
    assert first.statistical_value == second.statistical_value


def test_select_model_returns_none_for_empty_history() -> None:
    assert select_model([], []) is None
