"""INT2 : auto-enregistrement d'une source d'insight proactif DETERMINISTE
du module `crm` dans `core.services.insight_source_registry`, appele
depuis `apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_insight_registration.register_ai_insight_sources()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_pipeline_conversion_
insight` enveloppe directement `apps.crm.services.reports.conversion_rate`
(CRM-CONV, deja teste) — aucun nouveau calcul de taux introduit ici, l'IA
se contente de decider QUAND ce chiffre deja calcule merite d'etre remonte
comme insight proactif (taux bas sur un volume non trivial d'opportunites
cloturees)."""

from __future__ import annotations

from decimal import Decimal

from apps.core.services.insight_source_registry import InsightCandidate, register_insight_source

# Seuils choisis et disclosed (aucune reference normative externe) : un
# taux de conversion sous 30% est retenu comme "bas", mais uniquement si
# calcule sur au moins 3 opportunites cloturees (evite un faux signal issu
# d'un tout petit echantillon, ex. 0/1 = 0%).
_LOW_CONVERSION_THRESHOLD_PCT = Decimal(30)
_MIN_CLOSED_LEADS_FOR_SIGNAL = 3


def _pipeline_conversion_insight(tenant_id: str) -> list[InsightCandidate]:
    from apps.crm.models import CrmPipeline
    from apps.crm.services.reports import conversion_rate

    candidates: list[InsightCandidate] = []
    for pipeline in CrmPipeline.objects.filter(tenant_id=tenant_id, is_active=True):
        stats = conversion_rate(pipeline)
        if stats["closed"] < _MIN_CLOSED_LEADS_FOR_SIGNAL:
            continue
        if stats["conversion_rate_pct"] >= _LOW_CONVERSION_THRESHOLD_PCT:
            continue

        candidates.append(
            InsightCandidate(
                category="crm",
                title=f"Taux de conversion bas — pipeline « {pipeline.name} »",
                body=(
                    f"Le pipeline « {pipeline.name} » affiche un taux de conversion de "
                    f"{stats['conversion_rate_pct']:.1f}% ({stats['won']} gagnee(s) sur "
                    f"{stats['closed']} opportunite(s) cloturee(s))."
                ),
                source_modules=["crm"],
            )
        )

    return candidates


def register_ai_insight_sources() -> None:
    register_insight_source(
        "crm.pipeline_conversion_trend",
        module="crm",
        label="Taux de conversion du pipeline commercial",
        function=_pipeline_conversion_insight,
    )
