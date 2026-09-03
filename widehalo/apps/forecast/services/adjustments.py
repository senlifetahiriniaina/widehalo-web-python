"""Ajustement humain (FOR-6 : « tracé — auteur, date, valeur avant/après,
motif — et réversible ; la prévision statistique reste consultable en
parallèle ») et mesure de son apport (FOR-7 : « erreur ajustée vs
statistique sur périodes échues »)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.forecast.models import ForSeriesForecast

if TYPE_CHECKING:
    from apps.core.models.user import User


def apply_adjustment(
    forecast: ForSeriesForecast, *, new_value: Decimal, reason: str, user: User
) -> ForSeriesForecast:
    """FOR-6 : n'écrase jamais `statistical_value` — ajoute une entrée à
    `adjustment_history` et positionne `adjusted_value`. Un motif vide est
    refusé (cahier : "saisie directe par période, motif obligatoire")."""
    if not reason.strip():
        raise ValidationError("Le motif de l'ajustement est obligatoire.")
    before = forecast.adjusted_value if forecast.adjusted_value is not None else forecast.statistical_value
    forecast.adjustment_history = [
        *forecast.adjustment_history,
        {
            "author_id": str(user.id),
            "author_email": user.email,
            "at": timezone.now().isoformat(),
            "before": str(before),
            "after": str(new_value),
            "reason": reason.strip(),
        },
    ]
    forecast.adjusted_value = new_value
    forecast.save(update_fields=["adjusted_value", "adjustment_history"])
    return forecast


def revert_adjustment(forecast: ForSeriesForecast, *, user: User, reason: str) -> ForSeriesForecast:
    """FOR-6 : « réversible » — revient à la prévision statistique, trace
    ce retour comme un ajustement à part entière (jamais une suppression
    silencieuse de l'historique)."""
    return apply_adjustment(
        forecast, new_value=forecast.statistical_value, reason=reason or "Retour à la prévision statistique", user=user
    )


def measure_adjustment_contribution(forecast: ForSeriesForecast, *, actual_value: Decimal) -> ForSeriesForecast:
    """FOR-7 : appelée une fois la période échue (l'actuel est connu) —
    compare l'erreur de la prévision statistique et celle (le cas échéant)
    de la valeur ajustée par rapport au réalisé."""
    if actual_value == 0:
        return forecast
    forecast.statistical_error_pct = abs(actual_value - forecast.statistical_value) / abs(actual_value) * 100
    if forecast.adjusted_value is not None:
        forecast.adjustment_error_pct = abs(actual_value - forecast.adjusted_value) / abs(actual_value) * 100
    forecast.save(update_fields=["statistical_error_pct", "adjustment_error_pct"])
    return forecast
