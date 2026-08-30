"""GW4 — Passerelle IA locale d'analyse de donnees conversationnelle. Point
d'entree unique : `ask(question, *, tenant, user, locale) -> AiDataQuery`.

**Decision architecturale actee avec l'utilisateur (avant tout code, cf.
plan section "Cadrage detaille de la passerelle IA locale d'analyse de
donnees")** : code Django integre dans `apps.ai`, appelant directement les
fonctions `services/reports.py` DEJA testees EN PROCESSUS (zero appel
reseau supplementaire, zero nouveau service a deployer/securiser) — PAS un
microservice FastAPI separe (la proposition litterale d'un document
externe, ecarte car concu pour un deploiement mono-tenant qui n'adresse
jamais la question RLS multi-tenant de ce depot). Le LLM n'a JAMAIS acces
SQL/ORM direct : il ne peut choisir qu'un `code` de tool explicite parmi
une liste blanche (`core.services.data_query_tool_registry`), jamais un
texte libre execute.

**Discipline "fallback-first" (identique a AI2-AI7)** : `get_budget_gated_
provider(tenant)` est TOUJOURS appele en premier. Si le provider resultant
est `StubAIProvider` (non configure OU budget epuise), `ask()` persiste et
renvoie IMMEDIATEMENT un `AiDataQuery` avec le message statique du stub,
`tools_called=[]`, `succeeded=False` — la boucle de tool-calling n'est
JAMAIS meme tentee dans ce cas (aucun sens a l'ouvrir sans fournisseur
reel capable de tool-calling).

**Filtrage par permission AVANT tout appel LLM (correctif de securite du
cadrage, cf. docstring de `data_query_tool_registry`)** : le catalogue de
tools presente au LLM est construit UNIQUEMENT a partir des tools dont
`user.has_perm(tool.required_permission)` est vrai. Un tool auquel
l'utilisateur n'a pas droit n'est jamais meme OFFERT comme option au LLM,
et ne peut donc jamais apparaitre dans `tools_called` — deny-by-default,
verifie explicitement par `apps.ai.tests.test_data_query_gateway::
test_tool_never_offered_without_permission`.

**Boucle bornee a `_MAX_TOOL_ROUND_TRIPS = 3`** : un aller-retour
question/tool-calls/reponse-du-LLM. Borne choisie pour laisser au LLM la
possibilite d'enchainer 2-3 tools distincts pour composer une reponse
(ex. CA puis marge) sans jamais tourner indefiniment sur un modele qui
insisterait a tort a rappeler des tools au-dela d'un nombre raisonnable —
au-dela de la borne, la boucle degrade PROPREMENT vers le dernier contenu
textuel disponible (ou un message explicite si aucun contenu n'a jamais
ete produit), jamais une exception.

**Validation des arguments** : chaque `ToolCall.arguments` propose par le
LLM est valide contre le `parameters_schema` (JSON Schema) du tool AVANT
tout appel reel, via un petit validateur maison (`_validate_arguments`
ci-dessous) — `jsonschema` n'est PAS une dependance de ce depot (verifie
dans `requirements/*.txt` avant d'ecrire ce fichier), une validation
minimale suffisante (types de base `string`/`object`/champs `required`,
`enum`) est ecrite ici plutot que d'ajouter une dependance pour ce seul
besoin, meme discipline que `apps.ai.services.usage_budget.estimate_
tokens` (heuristique volontairement simple, disclosed). Un argument
invalide fait echouer CE tool call proprement (ignore, journalise en
warning) — jamais une valeur devinee, jamais une exception qui romprait la
boucle."""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.ai.models import AiDataQuery, AiRequest
from apps.ai.services.usage_budget import estimate_tokens, get_budget_gated_provider, record_request
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProviderError, StubAIProvider, ToolDefinition
from apps.core.services.data_query_tool_registry import DataQueryTool, list_data_query_tools

logger = logging.getLogger(__name__)

# Nombre maximal d'allers-retours question/tool-calls avec le LLM — cf.
# docstring de module pour le raisonnement. Une valeur codee en dur et
# nommee plutot qu'un parametre de settings : ce n'est pas un reglage de
# deploiement, c'est une garantie de terminaison de la boucle.
_MAX_TOOL_ROUND_TRIPS = 3

_UNABLE_TO_COMPLETE_FR = (
    "Impossible de terminer l'analyse demandee pour le moment — reessayez plus tard."
)


def _filtered_tools_for_user(user: User) -> list[DataQueryTool]:
    """Correctif de securite du cadrage (cf. docstring de module) : SEULS
    les tools dont l'utilisateur possede `required_permission` sont
    retenus — appele AVANT toute construction de `ToolDefinition`, un tool
    filtre ici n'est donc jamais meme serialise pour le LLM."""
    return [tool for tool in list_data_query_tools() if user.has_perm(tool.required_permission)]


def _to_tool_definition(tool: DataQueryTool) -> ToolDefinition:
    return ToolDefinition(
        name=tool.code, description=tool.description, parameters_schema=tool.parameters_schema
    )


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> bool:
    """Validation JSON Schema MINIMALE (pas de dependance `jsonschema`,
    absente de ce depot) : verifie uniquement ce dont les tools de GW3 ont
    besoin — champs `required` presents, type `string`/`object`/`number`/
    `boolean` de base par propriete declaree, et `enum` le cas echeant.
    Volontairement PAS une implementation complete du standard JSON Schema
    (pas de validation recursive de sous-objets/tableaux) : les schemas
    reels de ce chantier (GW3) sont tous plats, un validateur plus riche
    serait de la portee non demandee a ce stade."""
    if not isinstance(arguments, dict):
        return False
    for required_field in schema.get("required", []):
        if required_field not in arguments:
            return False
    properties: dict[str, Any] = schema.get("properties", {})
    _type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for field_name, value in arguments.items():
        field_schema = properties.get(field_name)
        if field_schema is None:
            continue
        expected_type = _type_map.get(field_schema.get("type", ""))
        if expected_type is not None and not isinstance(value, expected_type):
            return False
        allowed_values = field_schema.get("enum")
        if allowed_values is not None and value not in allowed_values:
            return False
    return True


def _run_tool_calling_loop(
    *,
    question: str,
    tenant: Tenant,
    user: User,
    provider: Any,
    tools: list[DataQueryTool],
) -> tuple[str, list[dict[str, Any]]]:
    """Boucle bornee a `_MAX_TOOL_ROUND_TRIPS` (cf. docstring de module).
    Renvoie `(answer, tools_called)` — degrade toujours proprement, jamais
    d'exception propagee a l'appelant (`ask()` capture neanmoins
    `AIProviderError` autour de cet appel par prudence, cf. plus bas)."""
    tools_by_code = {tool.code: tool for tool in tools}
    tool_definitions = [_to_tool_definition(tool) for tool in tools]
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tools_called: list[dict[str, Any]] = []
    last_content: str | None = None

    for _round_trip in range(_MAX_TOOL_ROUND_TRIPS):
        result = provider.complete_with_tools(messages, tool_definitions)
        if result.content:
            last_content = result.content
        if not result.tool_calls:
            return last_content or _UNABLE_TO_COMPLETE_FR, tools_called

        messages.append(
            {
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in result.tool_calls
                ],
            }
        )
        for call in result.tool_calls:
            tool = tools_by_code.get(call.name)
            if tool is None:
                # Nom de tool hallucine par le LLM, ou tool reel mais jamais
                # OFFERT (utilisateur sans la permission requise) — dans les
                # deux cas, ignore et journalise, jamais une valeur devinee.
                logger.warning(
                    "Tool '%s' propose par le LLM introuvable dans le catalogue filtre "
                    "(hallucine, ou hors permission de l'utilisateur) — ignore.",
                    call.name,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps({"error": "tool inconnu ou non autorise"}),
                    }
                )
                continue
            if not _validate_arguments(tool.parameters_schema, call.arguments):
                logger.warning(
                    "Arguments invalides pour le tool '%s' proposes par le LLM : %s — ignore.",
                    call.name,
                    call.arguments,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps({"error": "arguments invalides"}),
                    }
                )
                continue
            try:
                rows = tool.function(tenant, user, **call.arguments)
            except Exception:
                logger.exception(
                    "Echec de l'execution du tool '%s' — ignore, la boucle continue.", call.name
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps({"error": "echec d'execution du tool"}),
                    }
                )
                continue
            tools_called.append({"code": call.name, "args": call.arguments})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(rows, default=str),
                }
            )

    # Borne atteinte : degrade proprement vers le dernier contenu textuel
    # disponible plutot que de continuer indefiniment (cf. docstring de
    # module) — jamais une exception pour ce seul depassement de borne.
    return last_content or _UNABLE_TO_COMPLETE_FR, tools_called


def ask(question: str, *, tenant: Tenant, user: User, locale: str) -> AiDataQuery:
    del locale  # reserve pour une future traduction du message de repli
    # (cf. `contextual_assistant._is_english`) — non exploite pour l'instant,
    # le message de repli statique reste en francais uniquement, disclosed
    # comme portee MVP (aucun besoin bilingue exprime pour ce chantier).
    provider = get_budget_gated_provider(tenant)

    if isinstance(provider, StubAIProvider):
        record = AiDataQuery.objects.create(
            tenant=tenant,
            question=question,
            tools_called=[],
            answer=provider.complete(""),
            succeeded=False,
            provider_backend="stub",
            created_by=user,
        )
        record_request(
            tenant,
            feature=AiRequest.FEATURE_DATA_QUERY,
            prompt_tokens_estimate=estimate_tokens(question),
            completion_tokens_estimate=0,
            provider=provider,
            succeeded=False,
            created_by=user,
        )
        return record

    tools = _filtered_tools_for_user(user)
    try:
        answer, tools_called = _run_tool_calling_loop(
            question=question, tenant=tenant, user=user, provider=provider, tools=tools
        )
        succeeded = True
    except AIProviderError:
        answer, tools_called = _UNABLE_TO_COMPLETE_FR, []
        succeeded = False

    record = AiDataQuery.objects.create(
        tenant=tenant,
        question=question,
        tools_called=tools_called,
        answer=answer,
        succeeded=succeeded,
        provider_backend=_resolve_backend_label(provider),
        created_by=user,
    )
    record_request(
        tenant,
        feature=AiRequest.FEATURE_DATA_QUERY,
        prompt_tokens_estimate=estimate_tokens(question),
        completion_tokens_estimate=estimate_tokens(answer),
        provider=provider,
        succeeded=succeeded,
        created_by=user,
    )
    return record


def _resolve_backend_label(provider: Any) -> str:
    # Meme raisonnement exact que `apps.ai.services.usage_budget.
    # _resolve_backend_label` (prive, non reexporte) : dupliquee ici plutot
    # que de rendre publique une fonction privee d'un autre module pour un
    # seul appel — meme choix pragmatique que toute fonction `_prefixee`
    # de ce depot qui reste interne a son module.
    from django.conf import settings

    config: dict[str, str] = getattr(settings, "AI_PROVIDER_CONFIG", {})
    return config.get("backend", "custom")


__all__ = ["ask"]
