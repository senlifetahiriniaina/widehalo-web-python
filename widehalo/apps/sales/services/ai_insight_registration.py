"""AI5 : auto-enregistrement d'une source d'insight proactif DETERMINISTE
du module `sales` dans `core.services.insight_source_registry`, appele
depuis `apps.py::ready()` — meme patron que `ai_anomaly_registration.
register_ai_anomaly_checks()`/`ai_context_registration.
register_ai_context()` deja etablis dans ce module.

**Angle distinct de `ai_anomaly_registration._check_forecast_gap` (AI3)** :
celle-ci signale un PROBLEME (capacite/delai fournisseur insuffisant,
`dominant_cause != "aucun"`). Cet insight-ci signale au contraire une
OPPORTUNITE : une prevision **future**, SANS ecart capacite/delai
(`dominant_cause == "aucun"`), dont le coefficient saisonnier deja calcule
par `services.forecast.seasonal_coefficient` (persiste dans `SalesForecast.
parameters["seasonal_coefficient"]`) indique un mois nettement au-dessus
de la moyenne du variant — jamais un nouveau calcul de saisonnalite, une
simple lecture d'un champ deja produit par `services.forecast.
build_forecast` (RG-SAL-7, S6)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source
from apps.sales.models import SalesForecast

# Seuil disclosed : un coefficient saisonnier >= 1.15 signifie "ce mois
# vend, historiquement, au moins 15% de plus que la moyenne des mois du
# variant" (cf. docstring `seasonal_coefficient`) — un ordre de grandeur
# jugé suffisamment marque pour justifier un signal proactif, sans
# pretendre a un seuil statistiquement optimise.
_SEASONAL_UPTICK_THRESHOLD = Decimal("1.15")


def _current_month_bucket() -> str:
    today = dt.date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _seasonal_demand_uptick(tenant_id: str) -> list[InsightCandidate]:
    candidates: list[InsightCandidate] = []
    forecasts = SalesForecast.objects.filter(
        tenant_id=tenant_id,
        qty_forecast__gt=0,
        period__gte=_current_month_bucket(),
        parameters__dominant_cause="aucun",
    )

    for forecast in forecasts:
        raw_coefficient = forecast.parameters.get("seasonal_coefficient")
        if raw_coefficient is None:
            continue
        try:
            coefficient = Decimal(str(raw_coefficient))
        except InvalidOperation:
            continue
        if coefficient < _SEASONAL_UPTICK_THRESHOLD:
            continue

        uptick_pct = ((coefficient - Decimal(1)) * Decimal(100)).quantize(Decimal("1"))
        candidates.append(
            InsightCandidate(
                category="ventes",
                title=f"Demande en hausse prevue pour {forecast.period}",
                body=(
                    f"La prevision de demande du produit {forecast.variant_id} pour "
                    f"{forecast.period} (quantite prevue {forecast.qty_forecast}) integre un "
                    f"coefficient saisonnier de {coefficient} (+{uptick_pct}% vs moyenne du "
                    "produit), sans ecart de capacite ou de delai fournisseur identifie — "
                    "une opportunite a anticiper cote approvisionnement/stock."
                ),
                source_modules=["sales"],
            )
        )
    return candidates


def register_ai_insight_sources() -> None:
    register_insight_source(
        "sales.seasonal_demand_uptick",
        module="sales",
        label="Hausse saisonniere de demande prevue",
        function=_seasonal_demand_uptick,
    )
