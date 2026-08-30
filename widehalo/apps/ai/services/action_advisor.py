"""AI7 — Advisor d'actions / next-best-action (cf. plan section « Module
`ai` (Intelligence artificielle transversale) »). Point d'entree unique :
`suggest(module, action, *, tenant, role_code) -> list[AiRecommendation]`.

**Discipline non negociable (identique a AI3/AI5, « explicabilite
d'abord ») : une recommandation est TOUJOURS decidee par une regle
DETERMINISTE, jamais par un LLM.** Contrairement a AI2 (assistant)/AI3
(narrative d'anomalie)/AI5 (synthese d'insights), ce chantier N'APPELLE
JAMAIS `get_budget_gated_provider` — aucun texte n'est genere par IA ici,
disclosed explicitement : le plan lui-meme qualifie ce mecanisme de
"regles deterministes simples ... pas un modele ML", une garantie plus
stricte que le reste du chantier (qui autorise une PROSE optionnelle
generee par IA en plus d'un calcul deterministe) — introduire un appel LLM
"juste pour une justification en une ligne" aurait ete un elargissement de
perimetre non demande par le plan, explicitement ecarte ici.

**Deux sources de candidats, combinees et bornees a 3 (cf. plan, "2-3
suggestions par contexte")** :
1. `core.services.automation_registry` (AUTO3, deja construit) : toute
   action DEJA enregistree pour le module courant (`list_registered_
   actions()` filtre par `module`) est une candidate naturelle de
   suggestion — "une action deja automatisable est un candidat naturel de
   suggestion" (citation du plan). Bornee aux 2 premieres actions par
   ordre alphabetique de code (deterministe) pour ne jamais, a elle seule,
   saturer les 3 emplacements disponibles si un module en enregistre
   davantage.
2. `core.services.advisor_rule_registry` (nouveau, ce chantier) : regles
   CONCRETES ecrites par chaque module metier (cf. docstring de module de
   ce registre pour le raisonnement de conception), executees ici via
   `list_advisor_rules_for_module(module)`.

**Isolation des echecs** : une exception levee par LA FONCTION d'une
regle enregistree (bug dans son propre adaptateur) est journalisee et
n'interrompt QUE cette regle — les autres regles/candidats continuent
d'etre traites normalement (meme discipline exacte que `apps.ai.services.
anomaly_detection.run_all_checks`/`automated_insights._collect_
deterministic_insights`). `suggest()` ne leve donc jamais d'exception cote
appelant, quel que soit l'etat des registres — un contexte sans aucun
candidat renvoie simplement une liste vide (jamais une erreur)."""

from __future__ import annotations

import logging

from django.utils.translation import gettext

from apps.ai.models import AiRecommendation
from apps.core.models.tenant import Tenant
from apps.core.services.advisor_rule_registry import (
    RecommendationCandidate,
    list_advisor_rules_for_module,
)
from apps.core.services.automation_registry import list_registered_actions

logger = logging.getLogger(__name__)

_MAX_RECOMMENDATIONS = 3
_MAX_AUTOMATION_CANDIDATES = 2


def _automation_candidates(module: str) -> list[RecommendationCandidate]:
    """Une action DEJA enregistree dans `automation_registry` pour ce
    module est une candidate naturelle de suggestion (cf. docstring de
    module) — jamais une nouvelle regle metier, un simple rapprochement
    par `module` sur un catalogue deja construit ailleurs (AUTO3)."""
    matching = [action for action in list_registered_actions() if action.module == module]
    candidates: list[RecommendationCandidate] = []
    for registered in matching[:_MAX_AUTOMATION_CANDIDATES]:
        candidates.append(
            RecommendationCandidate(
                label=gettext("Automatiser : %(label)s") % {"label": registered.label},
                target_module=registered.module,
                target_action_code=registered.code,
            )
        )
    return candidates


def _rule_candidates(
    tenant_id: str, module: str, action: str, role_code: str
) -> list[RecommendationCandidate]:
    candidates: list[RecommendationCandidate] = []
    for registered in list_advisor_rules_for_module(module):
        try:
            candidates.extend(registered.function(tenant_id, action, role_code))
        except Exception:
            logger.exception(
                "Echec de la regle d'advisor '%s' (module %s) pour le contexte %s/%s — "
                "ignoree, les autres regles continuent.",
                registered.code,
                registered.module,
                module,
                action,
            )
            continue
    return candidates


def _persist_candidate(
    tenant: Tenant, *, module: str, action: str, role_code: str, candidate: RecommendationCandidate
) -> AiRecommendation:
    return AiRecommendation.objects.create(
        tenant=tenant,
        context_module=module,
        context_action=action,
        role_code=role_code,
        label=candidate.label,
        target_module=candidate.target_module,
        target_action_code=candidate.target_action_code,
    )


def suggest(module: str, action: str, *, tenant: Tenant, role_code: str) -> list[AiRecommendation]:
    """Combine les candidats du catalogue `automation_registry` et des
    regles enregistrees dans `advisor_rule_registry` pour le contexte
    `module`/`action`/`role_code`, persiste jusqu'a 3 `AiRecommendation`
    (cf. docstring de module) et les renvoie. Ne leve jamais l'exception
    d'une regle individuelle."""
    candidates = [
        *_rule_candidates(str(tenant.id), module, action, role_code),
        *_automation_candidates(module),
    ]
    created = [
        _persist_candidate(tenant, module=module, action=action, role_code=role_code, candidate=c)
        for c in candidates[:_MAX_RECOMMENDATIONS]
    ]
    return created


__all__ = ["suggest"]
