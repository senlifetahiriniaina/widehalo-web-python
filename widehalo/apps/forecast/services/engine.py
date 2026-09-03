"""Moteur statistique (cahier Phase 2 §13.2, §11.3 : « référence naïve
saisonnière, moyenne mobile, lissages exponentiels simple/double/triple,
régression avec régresseurs de calendrier — ML/forêts/gradient/réseaux
explicitement écartés, aucun gain démontrable, perte d'explicabilité
rédhibitoire »). Calcul interne en `float` (statistique, pas une écriture
comptable — `Decimal` reste la frontière de stockage/affichage,
`apps.forecast.models.ForSeriesForecast`), converti en `Decimal` en sortie
de `select_model`.

**Sélection reproductible (FOR-3)** : `select_model` rétrotests TOUS les
modèles candidats sur la même fenêtre glissante et choisit le score le
plus bas — aucun aléa, un même historique produit toujours la même
sélection."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

SEASON_LENGTH = 12  # maille mensuelle — un cycle annuel complet
MIN_HISTORY_FOR_SEASONALITY = 2 * SEASON_LENGTH  # H10 : deux cycles annuels complets


def _to_float(values: list[Decimal]) -> list[float]:
    return [float(v) for v in values]


def naive_seasonal(history: list[float]) -> float:
    """Valeur observée `SEASON_LENGTH` périodes plus tôt — repli sur la
    dernière valeur connue si l'historique est trop court pour un cycle
    complet (H10, « historique insuffisant -> pas de composante
    saisonnière, et l'écran le dit »)."""
    if len(history) >= SEASON_LENGTH:
        return history[-SEASON_LENGTH]
    return history[-1] if history else 0.0


def moving_average(history: list[float], window: int = 3) -> float:
    window = min(window, len(history)) or 1
    tail = history[-window:]
    return sum(tail) / len(tail) if tail else 0.0


def simple_exponential_smoothing(history: list[float], alpha: float = 0.3) -> float:
    if not history:
        return 0.0
    level = history[0]
    for value in history[1:]:
        level = alpha * value + (1 - alpha) * level
    return level


def double_exponential_smoothing(history: list[float], alpha: float = 0.3, beta: float = 0.1) -> float:
    """Lissage de Holt (tendance linéaire)."""
    if not history:
        return 0.0
    if len(history) == 1:
        return history[0]
    level = history[0]
    trend = history[1] - history[0]
    for value in history[1:]:
        previous_level = level
        level = alpha * value + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
    return level + trend


def triple_exponential_smoothing(
    history: list[float],
    alpha: float = 0.3,
    beta: float = 0.1,
    gamma: float = 0.1,
    season_length: int = SEASON_LENGTH,
) -> float:
    """Lissage de Holt-Winters (additif) — nécessite au moins deux cycles
    saisonniers complets, cf. `select_model`."""
    if len(history) < 2 * season_length:
        return double_exponential_smoothing(history, alpha, beta)

    seasonal = [
        sum(history[i] for i in range(s, len(history), season_length))
        / len([i for i in range(s, len(history), season_length)])
        for s in range(season_length)
    ]
    overall_avg = sum(seasonal) / season_length
    seasonal = [s - overall_avg for s in seasonal]

    level = history[0]
    trend = (sum(history[season_length : 2 * season_length]) - sum(history[:season_length])) / (
        season_length**2
    )
    for i, value in enumerate(history):
        season_index = i % season_length
        previous_level = level
        level = alpha * (value - seasonal[season_index]) + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
        seasonal[season_index] = gamma * (value - level) + (1 - gamma) * seasonal[season_index]

    next_season_index = len(history) % season_length
    return level + trend + seasonal[next_season_index]


def regression_calendaire(history: list[float], month_indices: list[int]) -> float:
    """Régression linéaire (tendance) + moyenne des écarts par mois de
    l'année (régresseur de calendrier simplifié — un vrai régresseur
    multi-facteurs, jours ouvrés compris, est une extension possible mais
    hors budget de ce premier chantier, disclosed)."""
    n = len(history)
    if n == 0:
        return 0.0
    if n == 1:
        return history[0]
    x_mean = (n - 1) / 2
    y_mean = sum(history) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(history))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator else 0.0
    intercept = y_mean - slope * x_mean
    trend_forecast = intercept + slope * n

    if len(set(month_indices)) < 2:
        return trend_forecast
    by_month: dict[int, list[float]] = {}
    for value, month in zip(history, month_indices):
        by_month.setdefault(month, []).append(value)
    residual_by_month = {
        month: (sum(vals) / len(vals)) - y_mean for month, vals in by_month.items()
    }
    next_month = month_indices[-1] % 12 + 1 if month_indices else 1
    return trend_forecast + residual_by_month.get(next_month, 0.0)


MODEL_FUNCTIONS = {
    "naive_saisonnier": lambda hist, months: naive_seasonal(hist),
    "moyenne_mobile": lambda hist, months: moving_average(hist),
    "lissage_simple": lambda hist, months: simple_exponential_smoothing(hist),
    "lissage_double": lambda hist, months: double_exponential_smoothing(hist),
    "lissage_triple": lambda hist, months: triple_exponential_smoothing(hist),
    "regression_calendaire": lambda hist, months: regression_calendaire(hist, months),
}


@dataclass
class BacktestResult:
    mae_pct: float
    weighted_pct: float
    bias_pct: float
    pairs: list[tuple[float, float]] = field(default_factory=list)


def backtest(history: list[float], months: list[int], model_code: str, *, test_periods: int) -> BacktestResult | None:
    """Rétrotest glissant (FOR-2/FOR-3, « sur les périodes échues, et non
    ajustement sur l'historique complet ») : pour chaque période des
    `test_periods` dernières, prédit avec UNIQUEMENT les données
    antérieures, jamais l'historique complet. `None` si l'historique est
    trop court pour tester ne serait-ce qu'une période."""
    model_fn = MODEL_FUNCTIONS[model_code]
    pairs: list[tuple[float, float]] = []
    min_train_size = 2
    start = max(len(history) - test_periods, min_train_size)
    for i in range(start, len(history)):
        train = history[:i]
        train_months = months[:i]
        if len(train) < min_train_size:
            continue
        predicted = model_fn(train, train_months)
        actual = history[i]
        pairs.append((actual, predicted))
    if not pairs:
        return None

    errors_pct = [abs(a - p) / a * 100 if a else 0.0 for a, p in pairs]
    mae_pct = sum(errors_pct) / len(errors_pct)
    total_actual = sum(a for a, _ in pairs)
    weighted_pct = (
        sum(abs(a - p) for a, p in pairs) / total_actual * 100 if total_actual else mae_pct
    )
    bias_terms = [(p - a) / a * 100 if a else 0.0 for a, p in pairs]
    bias_pct = sum(bias_terms) / len(bias_terms)
    return BacktestResult(mae_pct=mae_pct, weighted_pct=weighted_pct, bias_pct=bias_pct, pairs=pairs)


@dataclass
class ModelSelection:
    selected_model: str
    selected_score: Decimal
    reference_naive_value: Decimal
    reference_naive_beats_selected: bool
    rejected_models: list[dict[str, str]]
    statistical_value: Decimal
    error_mae_pct: Decimal | None
    error_weighted_pct: Decimal | None
    error_bias_pct: Decimal | None
    insufficient_history_for_seasonality: bool
    test_window_start: dt.date
    test_window_end: dt.date


def select_model(
    history_periods: list[dt.date], history_values: list[Decimal], *, test_periods: int = 6
) -> ModelSelection | None:
    """FOR-1/FOR-2/FOR-3 : calcule la référence naïve, rétrotest tous les
    modèles candidats sur la MÊME fenêtre glissante, retient le score le
    plus bas — `None` si l'historique est vide."""
    if not history_periods:
        return None
    history = _to_float(history_values)
    months = [p.month for p in history_periods]
    insufficient = len(history) < MIN_HISTORY_FOR_SEASONALITY

    candidates = list(MODEL_FUNCTIONS)
    if insufficient:
        candidates = [c for c in candidates if c not in ("naive_saisonnier", "lissage_triple")]
        if not candidates:
            candidates = ["moyenne_mobile"]

    scored: dict[str, BacktestResult] = {}
    for code in candidates:
        result = backtest(history, months, code, test_periods=test_periods)
        if result is not None:
            scored[code] = result

    naive_result = backtest(history, months, "naive_saisonnier", test_periods=test_periods)
    reference_naive_value = Decimal(str(round(naive_seasonal(history), 4)))

    if not scored:
        value = Decimal(str(round(history[-1], 4)))
        return ModelSelection(
            selected_model="naive_saisonnier",
            selected_score=Decimal("0"),
            reference_naive_value=reference_naive_value,
            reference_naive_beats_selected=True,
            rejected_models=[],
            statistical_value=value,
            error_mae_pct=None,
            error_weighted_pct=None,
            error_bias_pct=None,
            insufficient_history_for_seasonality=insufficient,
            test_window_start=history_periods[0],
            test_window_end=history_periods[-1],
        )

    best_code = min(scored, key=lambda c: scored[c].mae_pct)
    best_result = scored[best_code]
    naive_mae = naive_result.mae_pct if naive_result else None
    beats_naive = naive_mae is None or best_result.mae_pct <= naive_mae
    if not beats_naive:
        best_code = "naive_saisonnier"
        best_result = naive_result

    predicted_value = MODEL_FUNCTIONS[best_code](history, months)
    rejected = [
        {"model": code, "score": str(round(result.mae_pct, 4))}
        for code, result in scored.items()
        if code != best_code
    ]
    window_start_index = max(len(history_periods) - test_periods, 0)

    return ModelSelection(
        selected_model=best_code,
        selected_score=Decimal(str(round(best_result.mae_pct, 4))),
        reference_naive_value=reference_naive_value,
        reference_naive_beats_selected=not beats_naive,
        rejected_models=rejected,
        statistical_value=Decimal(str(round(predicted_value, 4))),
        error_mae_pct=Decimal(str(round(best_result.mae_pct, 4))),
        error_weighted_pct=Decimal(str(round(best_result.weighted_pct, 4))),
        error_bias_pct=Decimal(str(round(best_result.bias_pct, 4))),
        insufficient_history_for_seasonality=insufficient,
        test_window_start=history_periods[window_start_index],
        test_window_end=history_periods[-1],
    )
