"""AI3 : auto-enregistrement d'une verification d'anomalie DETERMINISTE
du module `sales` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()`/`reports_registration.register_reports()` deja
etablis dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_forecast_
gap` lit simplement le champ `parameters["dominant_cause"]` DEJA calcule
et persiste par `services.forecast.build_forecast` (RG-SAL-7, S6) sur
chaque `SalesForecast` existant du tenant — jamais un nouveau calcul de
prevision/ecart invente ici, ni un nouvel appel a `build_forecast` (qui
recalculerait inutilement sur des donnees potentiellement deja a jour).

`dominant_cause` ne vaut jamais `"aucun"` que dans deux cas (cf. docstring
`build_forecast`) :
- `"capacite"` : capacite atelier totale nulle alors qu'une demande non
  nulle est prevue — aucune capacite de production propre, severite
  `SEVERITY_HIGH` (risque de rupture totale, pas seulement un retard) ;
- `"delai_fournisseur"` : le delai fournisseur connu depasse le nombre de
  jours restants avant le debut de la periode — matiere commandee trop
  tard vu le lead time, severite `SEVERITY_MEDIUM` (delai a rattraper,
  pas une impossibilite totale de produire)."""

from __future__ import annotations

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)
from apps.sales.models import SalesForecast

_CAUSE_CAPACITY = "capacite"
_CAUSE_SUPPLIER_LEAD_TIME = "delai_fournisseur"

_SEVERITY_BY_CAUSE = {
    _CAUSE_CAPACITY: SEVERITY_HIGH,
    _CAUSE_SUPPLIER_LEAD_TIME: SEVERITY_MEDIUM,
}

_DESCRIPTION_BY_CAUSE = {
    _CAUSE_CAPACITY: "aucune capacite d'atelier propre disponible pour honorer cette demande",
    _CAUSE_SUPPLIER_LEAD_TIME: (
        "delai fournisseur connu superieur au temps restant avant la periode"
    ),
}


def _check_forecast_gap(tenant_id: str) -> list[AnomalyCandidate]:
    candidates: list[AnomalyCandidate] = []
    forecasts = SalesForecast.objects.filter(tenant_id=tenant_id, qty_forecast__gt=0).exclude(
        parameters__dominant_cause="aucun"
    )

    for forecast in forecasts:
        cause = forecast.parameters.get("dominant_cause")
        severity = _SEVERITY_BY_CAUSE.get(cause)
        if severity is None:
            # Cause inconnue (evolution future de `build_forecast` non
            # encore reflet ici) — ignore plutot que de fabriquer une
            # severite arbitraire.
            continue
        candidates.append(
            AnomalyCandidate(
                content_type_label="sales.salesforecast",
                object_id=str(forecast.id),
                severity=severity,
                description=(
                    f"Ecart capacite/delai sur la prevision {forecast.period} du produit "
                    f"{forecast.variant_id} (quantite prevue {forecast.qty_forecast}) : "
                    f"{_DESCRIPTION_BY_CAUSE[cause]}."
                ),
            )
        )
    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "sales.forecast_gap",
        module="sales",
        label="Ecart capacite/delai fournisseur sur une prevision de demande",
        function=_check_forecast_gap,
    )
