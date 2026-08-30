"""AI5 : auto-enregistrement d'une source d'insight proactif DETERMINISTE
du module `strategy` dans `core.services.insight_source_registry`, appele
depuis `apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()` deja etabli dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_capacity_trend`
appelle simplement `services.capacity_review.build_capacity_outlook(...,
notify=False)` (CAP1-2, deja construit) et lit le `workload_pct` DEJA
calcule de la premiere et de la derniere semaine de l'horizon — jamais un
nouveau calcul de charge/capacite invente ici. `notify=False` evite de
declencher une seconde fois la notification de surcharge propre a
`capacity_review` (celle-ci reste de la responsabilite de l'ecran/rapport
`CAP-90J` qui l'invoque avec `notify=True`, cf. sa docstring) — cet
insight-ci porte un signal DIFFERENT (tendance d'utilisation sur
l'horizon), pas une alerte de depassement de seuil."""

from __future__ import annotations

from decimal import Decimal

from apps.core.models.tenant import Tenant
from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source
from apps.strategy.services.capacity_review import build_capacity_outlook

# Seuil disclosed : une variation de charge planifiee de moins de 10
# points de pourcentage entre la premiere et la derniere semaine de
# l'horizon est consideree comme un plateau (pas de signal a remonter) —
# ordre de grandeur choisi pour eviter un insight quotidien sur un bruit
# de quelques points, sans pretendre a un seuil statistiquement optimise.
_TREND_THRESHOLD_PCT = Decimal("10")


def _capacity_trend(tenant_id: str) -> list[InsightCandidate]:
    tenant = Tenant.objects.get(id=tenant_id)
    outlook = build_capacity_outlook(tenant, notify=False)
    weeks = outlook["weeks"]
    if not weeks:
        return []

    first_week = weeks[0]
    last_week = weeks[-1]
    if first_week["capacity_hours"] <= 0 or last_week["capacity_hours"] <= 0:
        # Aucune capacite atelier propre — le taux de charge n'a aucun
        # sens ici (division par une capacite nulle deja evitee cote
        # `build_capacity_outlook`, qui renvoie 0% dans ce cas).
        return []

    delta_pct = last_week["workload_pct"] - first_week["workload_pct"]
    if abs(delta_pct) < _TREND_THRESHOLD_PCT:
        return []

    direction = "hausse" if delta_pct > 0 else "baisse"
    return [
        InsightCandidate(
            category="production",
            title=f"Taux de charge en {direction} sur l'horizon {outlook['horizon_days']} jours",
            body=(
                f"Le taux de charge planifie passe de {first_week['workload_pct']}% "
                f"(semaine du {first_week['week_start']}) a {last_week['workload_pct']}% "
                f"(semaine du {last_week['week_start']}), soit une variation de "
                f"{delta_pct:+}% sur l'horizon de {outlook['horizon_days']} jours."
            ),
            source_modules=["strategy"],
        )
    ]


def register_ai_insight_sources() -> None:
    register_insight_source(
        "strategy.capacity_trend",
        module="strategy",
        label="Tendance de taux de charge sur l'horizon 90 jours",
        function=_capacity_trend,
    )
