"""INT2 : auto-enregistrement d'une source d'insight proactif DETERMINISTE
du module `feasibility` dans `core.services.insight_source_registry`,
appele depuis `apps.py::ready()` — meme patron exact que
`apps.helpdesk.services.ai_insight_registration.register_ai_insight_
sources()` deja etabli dans ce chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_low_margin_studies_
insight` ne fait QUE surfacer `FeaStudyLine.computed_margin_pct`, DEJA
calcule par `services/simulation.py::simulate_study_line` (JAMAIS saisi a
la main, cf. docstring `models.py`) — aucun nouveau calcul de marge n'est
introduit ici, uniquement une decision de QUAND ce chiffre deja calcule
merite d'etre remonte comme insight proactif (une etude recemment
completee contient au moins une ligne a marge faible/negative)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.utils import timezone

from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source

_WINDOW_DAYS = 30
# Seuil choisi et disclosed (aucune reference normative externe) : une
# marge simulee sous 10% est retenue comme "faible" (couvre aussi les
# marges negatives, `computed_margin_pct` pouvant etre negatif si le cout
# depasse le CA hypothese).
_LOW_MARGIN_THRESHOLD_PCT = Decimal(10)


def _low_margin_studies_insight(tenant_id: str) -> list[InsightCandidate]:
    from apps.feasibility.models import FeaStudy, FeaStudyLine

    since = timezone.now() - dt.timedelta(days=_WINDOW_DAYS)
    completed_study_ids = FeaStudy.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
        status=FeaStudy.STATUS_COMPLETED,
        updated_at__gte=since,
    ).values_list("id", flat=True)

    low_margin_study_count = (
        FeaStudyLine.objects.filter(
            tenant_id=tenant_id,
            is_active=True,
            study_id__in=completed_study_ids,
            computed_margin_pct__lt=_LOW_MARGIN_THRESHOLD_PCT,
        )
        .values("study_id")
        .distinct()
        .count()
    )

    if low_margin_study_count == 0:
        return []

    return [
        InsightCandidate(
            category="feasibility",
            title="Etudes de faisabilite a marge simulee faible",
            body=(
                f"{low_margin_study_count} etude(s) de faisabilite completee(s) sur "
                f"les {_WINDOW_DAYS} derniers jours contiennent au moins une ligne "
                f"dont la marge simulee est inferieure a {_LOW_MARGIN_THRESHOLD_PCT}%."
            ),
            source_modules=["feasibility"],
        )
    ]


def register_ai_insight_sources() -> None:
    register_insight_source(
        "feasibility.low_margin_studies",
        module="feasibility",
        label="Etudes de faisabilite a marge simulee faible",
        function=_low_margin_studies_insight,
    )
