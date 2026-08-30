"""AI5 — Insights proactifs automatises (cf. plan section « Module `ai`
(Intelligence artificielle transversale) »). Point d'entree unique :
`generate(tenant)`.

**Discipline non negociable (identique a AI3, cf. docstring de
`apps.core.services.insight_source_registry`) : le CALCUL de chaque
insight est TOUJOURS deterministe.** Cette fonction ne fait qu'executer
les fonctions DEJA enregistrees par chaque module metier
(`register_insight_source`, appele depuis leur propre `apps.py::ready()`)
et persister les `InsightCandidate` qu'elles ont deja calcules — jamais un
appel LLM pour PRODUIRE un insight deterministe.

**Isolation des echecs** : une exception levee par LA FONCTION d'un
module (bug dans son propre adaptateur) est journalisee et n'interrompt
QUE cette source — les autres sources enregistrees continuent d'etre
executees normalement (meme discipline exacte que `apps.ai.services.
anomaly_detection.run_all_checks`).

**Synthese cross-module optionnelle (`is_ai_generated=True`,
`category="synthese"`)** : APRES avoir persiste tous les insights
deterministes du run, si (et seulement si) :
1. au moins DEUX modules distincts (`source_modules`) ont contribue un
   insight dans CE run, ET
2. un fournisseur IA reel est disponible (`get_budget_gated_provider`
   renvoie autre chose qu'un `StubAIProvider`) ;
alors un unique appel LLM est tente pour produire une courte observation
qualitative reliant les insights deterministes deja generes (titres/corps
en texte, jamais les objets `AiInsight` eux-memes). **Simplification
assumee et disclosed** : ceci n'est PAS une correlation statistique
calculee (aucun coefficient, aucun decalage temporel n'est mesure ici) —
le prompt demande explicitement au LLM une observation qualitative en
langage clair, jamais un chiffre invente. Toute `AIProviderError`, ou
l'absence d'un provider reel, ou moins de deux modules contributeurs,
fait simplement SAUTER cette etape (aucun insight de synthese cree) sans
jamais bloquer les insights deterministes deja persistes.

**Notification (choix disclosed)** : UNE notification `direction` unique
par appel de `generate()`, recapitulant le nombre d'insights crees —
`apps.core.services.notifications.notify_role` n'offre pas de mecanisme
de regroupement horaire cote emission (celui-ci, `group_hourly()`, agit en
aval sur les `Notification` deja creees, pour l'envoi e-mail) ; emettre
UNE notification par run (plutot qu'une par insight individuel) est donc
le choix le plus simple qui evite un flot d'une notification par insight
a chaque execution planifiee (qui peut en produire plusieurs d'un coup) —
coherent avec `apps.strategy.services.capacity_review._notify_overload`
qui notifie egalement une fois par run (liste agregee), jamais par
element individuel. Aucune notification n'est emise si `generate()` n'a
produit aucun insight."""

from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from apps.ai.models import AiInsight, AiRequest
from apps.ai.services.usage_budget import estimate_tokens, get_budget_gated_provider, record_request
from apps.core.models.tenant import Tenant
from apps.core.services.ai_assistant import AIProviderError, StubAIProvider
from apps.core.services.insight_source_registry import InsightCandidate, list_insight_sources
from apps.core.services.notifications import notify_role

logger = logging.getLogger(__name__)

_SYNTHESIS_CATEGORY = "synthese"
_SYNTHESIS_MAX_TOKENS = 200
_NOTIFICATION_ROLE = "direction"


def _persist_candidate(
    tenant: Tenant, candidate: InsightCandidate, *, is_ai_generated: bool
) -> AiInsight:
    return AiInsight.objects.create(
        tenant=tenant,
        category=candidate.category,
        title=candidate.title,
        body=candidate.body,
        source_modules=list(candidate.source_modules),
        is_ai_generated=is_ai_generated,
    )


def _collect_deterministic_insights(tenant: Tenant) -> list[AiInsight]:
    created: list[AiInsight] = []
    for registered in list_insight_sources():
        try:
            candidates = registered.function(str(tenant.id))
        except Exception:
            logger.exception(
                "Echec de la source d'insight '%s' (module %s) pour le tenant %s — "
                "ignoree, les autres sources continuent.",
                registered.code,
                registered.module,
                tenant.id,
            )
            continue

        for candidate in candidates:
            created.append(_persist_candidate(tenant, candidate, is_ai_generated=False))

    return created


def _build_synthesis_prompt(insights: list[AiInsight]) -> str:
    lines = [
        "Voici plusieurs observations deja calculees automatiquement pour cette "
        "entreprise, provenant de modules differents. En 2 a 3 phrases claires, "
        "note UNIQUEMENT une eventuelle connexion plausible entre elles, en "
        "langage qualitatif — jamais un coefficient de correlation ni un delai "
        "chiffre que tu n'as pas reellement calcule :"
    ]
    for insight in insights:
        lines.append(f"- [{insight.category}] {insight.title} : {insight.body}")
    return "\n".join(lines)


def _distinct_source_modules(insights: list[AiInsight]) -> set[str]:
    modules: set[str] = set()
    for insight in insights:
        modules.update(insight.source_modules)
    return modules


def _generate_synthesis(tenant: Tenant, insights: list[AiInsight]) -> AiInsight | None:
    """Insight de synthese optionnel — cf. docstring de module. Renvoie
    `None` sur tout chemin de repli (moins de deux modules contributeurs,
    provider stub, `AIProviderError`) plutot que de fabriquer un insight
    de substitution."""
    contributing_modules = _distinct_source_modules(insights)
    if len(contributing_modules) < 2:
        return None

    provider = get_budget_gated_provider(tenant)
    if isinstance(provider, StubAIProvider):
        return None

    prompt = _build_synthesis_prompt(insights)
    try:
        completion = provider.complete(prompt, max_tokens=_SYNTHESIS_MAX_TOKENS)
    except AIProviderError:
        record_request(
            tenant,
            feature=AiRequest.FEATURE_INSIGHT,
            prompt_tokens_estimate=estimate_tokens(prompt),
            completion_tokens_estimate=0,
            provider=provider,
            succeeded=False,
        )
        return None

    record_request(
        tenant,
        feature=AiRequest.FEATURE_INSIGHT,
        prompt_tokens_estimate=estimate_tokens(prompt),
        completion_tokens_estimate=estimate_tokens(completion),
        provider=provider,
        succeeded=True,
    )

    return _persist_candidate(
        tenant,
        InsightCandidate(
            category=_SYNTHESIS_CATEGORY,
            title="Observation cross-module",
            body=completion,
            source_modules=sorted(contributing_modules),
        ),
        is_ai_generated=True,
    )


def _notify_insights_created(tenant: Tenant, insights: list[AiInsight]) -> None:
    payload = {
        "insight_count": len(insights),
        "categories": sorted({insight.category for insight in insights}),
        "message": _("%(count)s nouvel(aux) insight(s) proactif(s) genere(s).")
        % {"count": len(insights)},
    }
    notify_role(str(tenant.id), _NOTIFICATION_ROLE, "ai.insight_generated", payload)


def generate(tenant: Tenant) -> list[AiInsight]:
    """Execute TOUTES les sources d'insight enregistrees dans
    `core.services.insight_source_registry` pour `tenant`, persiste
    chaque `InsightCandidate` renvoye en `AiInsight`, tente ENSUITE une
    synthese cross-module optionnelle, puis notifie `direction` d'un seul
    tenant (cf. docstring de module). Ne leve jamais l'exception d'une
    source individuelle."""
    created = _collect_deterministic_insights(tenant)

    synthesis = _generate_synthesis(tenant, created)
    if synthesis is not None:
        created.append(synthesis)

    if created:
        _notify_insights_created(tenant, created)

    return created


__all__ = ["generate"]
