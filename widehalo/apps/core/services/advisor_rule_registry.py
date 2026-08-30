"""Registre central des regles d'advisor d'actions (module `ai`, chantier
AI7 « Advisor d'actions (next-best-action) ») — meme patron exact que
`apps.core.services.anomaly_registry`/`insight_source_registry`/
`automation_registry` : chaque module metier enregistre un adaptateur MINCE
vers une regle DETERMINISTE ecrite dans SON PROPRE module (comptage/etat
deja disponible, jamais une nouvelle logique metier ecrite pour ce
registre) via son propre `apps.py::ready()` — `apps.ai` ne decide JAMAIS
quoi recommander via un LLM, il se contente d'executer les regles
enregistrees et de persister leurs resultats (`AiRecommendation`).

**Decision de conception actee (disclosed)** : un nouveau registre plutot
que quelques regles codees en dur directement dans `apps.ai.services.
action_advisor` — choisi pour rester coherent avec l'ETABLISSEMENT deja
tres marque de ce meme patron dans ce chantier (`anomaly_registry` en AI3,
`insight_source_registry` en AI5, tous deux calques sur `automation_
registry`/`reports_registry` anterieurs) : un troisieme registre suivant
exactement la meme forme est plus previsible pour un futur contributeur
qu'une exception ad hoc, meme si le volume de regles a livrer ici (2-3,
cf. plan) resterait trivial a coder en dur. `apps.ai.services.
action_advisor` complete neanmoins ce registre par une source integree
supplementaire — le catalogue `core.services.automation_registry` deja
construit (AUTO3) — lue directement, SANS passer par ce registre : une
action deja automatisable pour le module courant est une candidate
naturelle de suggestion par construction, cf. docstring de
`action_advisor`.

**Design contextuel (disclosed)** : contrairement a `anomaly_registry`/
`insight_source_registry` (une fonction enregistree est executee pour TOUT
le tenant a chaque run, sans notion de page/ecran), une regle d'advisor
est intrinsequement liee au CONTEXTE module/action/role de l'ecran en
cours (meme grain que `apps.ai.services.contextual_assistant.assist`) :
chaque fonction enregistree recoit donc `(tenant_id, action, role_code)`
en plus du filtrage par `module` deja fait par le registre lui-meme
(`list_advisor_rules_for_module`), et decide ELLE-MEME, avec ces trois
informations, si/quoi recommander (une liste vide est un resultat normal
si le contexte ne s'y prete pas — jamais une exception)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationCandidate:
    """Une recommandation DEJA decidee par une regle deterministe d'un
    module metier — `ai` ne fait que la persister (`AiRecommendation`)."""

    label: str
    target_module: str
    target_action_code: str = ""


# Une regle recoit (tenant_id, action, role_code) et renvoie la liste des
# recommandations qu'elle a deja decidees deterministiquement pour ce
# contexte — jamais un appel LLM a l'interieur de cette fonction.
AdvisorRuleFunction = Callable[[str, str, str], list[RecommendationCandidate]]


@dataclass(frozen=True)
class RegisteredAdvisorRule:
    code: str
    module: str
    label: str
    function: AdvisorRuleFunction


_REGISTRY: dict[str, RegisteredAdvisorRule] = {}


def register_advisor_rule(
    code: str, *, module: str, label: str, function: AdvisorRuleFunction
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree)."""
    _REGISTRY[code] = RegisteredAdvisorRule(
        code=code, module=module, label=label, function=function
    )


def get_advisor_rule(code: str) -> RegisteredAdvisorRule | None:
    return _REGISTRY.get(code)


def list_advisor_rules() -> list[RegisteredAdvisorRule]:
    return sorted(_REGISTRY.values(), key=lambda r: r.code)


def list_advisor_rules_for_module(module: str) -> list[RegisteredAdvisorRule]:
    return [rule for rule in list_advisor_rules() if rule.module == module]


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
