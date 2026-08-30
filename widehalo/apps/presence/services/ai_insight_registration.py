"""AI5 : auto-enregistrement d'une source d'insight proactif DETERMINISTE
du module `presence` dans `core.services.insight_source_registry`, appele
depuis `apps.py::ready()` — meme patron que `ai_context_registration.
register_ai_context()` deja etabli dans ce module.

**Adaptateur mince, pas une nouvelle regle metier** : `_absence_trend`
appelle deux fois `services.public.get_tenant_absence_days_in_period`
(gap DEJA construit pour le chantier CAP1-2, cf. `apps.strategy.services.
capacity_review`) sur deux fenetres glissantes de 7 jours consecutives
(semaine courante vs semaine precedente) et compare les deux totaux DEJA
calcules — jamais un nouveau calcul de taux d'absenteisme/turnover invente
ici (aucun signal de ce type n'existe encore ailleurs dans ce depot)."""

from __future__ import annotations

import datetime as dt

from apps.core.models.tenant import Tenant
from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source
from apps.presence.services.public import get_tenant_absence_days_in_period

_WINDOW_DAYS = 7


def _absence_trend(tenant_id: str) -> list[InsightCandidate]:
    tenant = Tenant.objects.get(id=tenant_id)
    today = dt.date.today()

    current_start = today - dt.timedelta(days=_WINDOW_DAYS - 1)
    current_days = get_tenant_absence_days_in_period(tenant, date_from=current_start, date_to=today)

    previous_end = current_start - dt.timedelta(days=1)
    previous_start = previous_end - dt.timedelta(days=_WINDOW_DAYS - 1)
    previous_days = get_tenant_absence_days_in_period(
        tenant, date_from=previous_start, date_to=previous_end
    )

    # Signal remonte uniquement en cas de HAUSSE reelle (jamais un
    # plateau/une baisse, ni une semaine sans aucune absence) — evite un
    # insight quotidien sur un volume d'absence stable ou nul.
    if current_days <= previous_days or current_days <= 0:
        return []

    return [
        InsightCandidate(
            category="rh",
            title="Hausse du volume d'absences sur la semaine",
            body=(
                f"Le volume d'absences valide sur les {_WINDOW_DAYS} derniers jours "
                f"({current_start} au {today}) est de {current_days} jour(s)-personne, contre "
                f"{previous_days} jour(s)-personne la semaine precedente "
                f"({previous_start} au {previous_end})."
            ),
            source_modules=["presence"],
        )
    ]


def register_ai_insight_sources() -> None:
    register_insight_source(
        "presence.absence_trend",
        module="presence",
        label="Tendance hebdomadaire du volume d'absences",
        function=_absence_trend,
    )
