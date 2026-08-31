"""Mecanisme generique de connecteur IA (chantier `projects`, PJ12) —
reutilisable par n'importe quel module metier futur, jamais couple a
`projects`. Meme discipline "stub par defaut / connecteur reel optionnel"
que `apps.core.services.whatsapp` (WhatsApp Business) et
`apps.purchase.services.price_watch` (veille prix) : lire leurs
docstrings respectives pour le meme raisonnement applique ailleurs dans
ce depot.

**Decision structurante** : DeepSeek, Kimi (Moonshot AI) et la plupart des
fournisseurs LLM tiers exposent une API "chat completions" compatible
OpenAI (meme forme de requete/reponse JSON) — un seul connecteur HTTP
parametre (`OpenAICompatibleAIProvider`) couvre donc TOUS ces fournisseurs,
plutot que d'ecrire une implementation par fournisseur.

`settings.AI_PROVIDER_CONFIG` (dict `str -> str`, VIDE par defaut dans
`config/settings/base.py`) est la SEULE source de configuration. Cles
attendues si l'utilisateur souhaite activer un connecteur reel :
- `base_url` : racine de l'API compatible OpenAI (ex.
  "https://api.deepseek.com/v1", "https://api.moonshot.cn/v1") ;
- `api_key` : cle d'API du fournisseur ;
- `model` : identifiant du modele a appeler (ex. "deepseek-chat",
  "moonshot-v1-8k") — optionnel, defaut "gpt-3.5-turbo" si absent (valeur
  neutre, jamais utilisee reellement sans `base_url`/`api_key`).

Tant que `base_url` ET `api_key` ne sont PAS tous deux renseignes,
`get_ai_provider()` retourne `StubAIProvider` — AUCUN appel reseau n'est
jamais effectue par defaut, dans aucun environnement (dev/test/prod)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-3.5-turbo"
_DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ToolDefinition:
    """Description d'un tool exposable au LLM, format "tool calling"
    standard compatible OpenAI (`type: "function"`) — cf. chantier
    "passerelle IA locale d'analyse de donnees" (GW1). `parameters_schema`
    est un JSON Schema strict (`{"type": "object", "properties": {...},
    "required": [...]}`), jamais un dict libre non valide."""

    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """Un appel de tool DEJA decide par le LLM — `arguments` est deja
    parse en dict (le connecteur reel deserialise le JSON texte renvoye par
    le fournisseur avant de construire cet objet, cf.
    `OpenAICompatibleAIProvider.complete_with_tools`)."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallResult:
    """Resultat d'un tour de conversation avec tool-calling : soit du
    texte final (`content`, `tool_calls` vide), soit une liste de tools que
    le LLM souhaite invoquer (`content` peut alors etre `None`) — jamais les
    deux formes melangees de facon ambigue, meme convention que le format
    de reponse OpenAI standard."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class AIProviderError(Exception):
    """Leve par un provider reel en cas d'echec (reseau, HTTP, reponse
    inattendue) — les fonctions IA de plus haut niveau (`apps.projects.
    services.ai_assistant`, futurs modules) DOIVENT capturer cette
    exception et degrader vers un message clair plutot que de laisser
    l'appelant planter (meme discipline que `PriceQuote.price=None` sur
    echec reseau dans `apps.purchase.services.price_watch`)."""


class AIProvider(Protocol):
    """Interface d'un fournisseur d'assistance IA generique — un seul
    point d'appel (`complete`), independant de tout module metier."""

    def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
        """Retourne le texte genere par le modele pour `prompt`. Ne DOIT
        jamais lever d'exception pour un cas "non configure" (le stub
        retourne un message explicite) ; un connecteur reel peut lever
        `AIProviderError` sur echec reseau/HTTP — a l'appelant de decider
        s'il capture ou laisse remonter."""
        ...

    def complete_with_tools(
        self, messages: list[dict[str, Any]], tools: list[ToolDefinition], *, max_tokens: int = 500
    ) -> ToolCallResult:
        """Extension ADDITIVE (GW1, passerelle IA locale d'analyse de
        donnees) — jamais un remplacement de `complete()` ci-dessus, deja
        consomme tel quel par AI2-AI7/`projects`. `messages` suit le format
        standard de conversation OpenAI (liste de `{"role": ..., "content":
        ...}`, roles `system`/`user`/`assistant`/`tool`) ; `tools` est DEJA
        filtree par permission par l'appelant (`apps.ai.services.
        data_query_gateway.ask`) AVANT d'arriver ici — ce Protocol ne fait
        aucun filtrage lui-meme, il transmet fidelement ce qu'on lui donne.
        Meme discipline d'erreurs que `complete()` : jamais d'exception pour
        un cas "non configure", `AIProviderError` seulement sur echec
        reseau/HTTP/reponse malformee d'un connecteur reel."""
        ...


class StubAIProvider:
    """Provider par defaut, actif tant qu'aucun connecteur reel n'est
    configure (cf. reserve de configuration en tete de ce fichier). NE
    FAIT RIGOUREUSEMENT AUCUN APPEL RESEAU — ni `requests`, ni `urllib`,
    ni aucune autre bibliotheque HTTP n'est invoquee ici. Retourne un
    message explicite, traduisible, invitant a configurer
    `settings.AI_PROVIDER_CONFIG`."""

    def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
        return str(
            _(
                "Assistance IA non configurée — renseigner settings.AI_PROVIDER_CONFIG "
                "(base_url, api_key, model) pour activer un connecteur reel."
            )
        )

    def complete_with_tools(
        self, messages: list[dict[str, Any]], tools: list[ToolDefinition], *, max_tokens: int = 500
    ) -> ToolCallResult:
        """Meme message que `complete()`, `tool_calls` toujours vide —
        RIGOUREUSEMENT AUCUN appel reseau (meme reserve de securite,
        verifiee par le meme patron de test que `complete()` : patch de
        `socket.socket` qui echoue le test si invoque)."""
        return ToolCallResult(content=self.complete(""), tool_calls=[])


class OpenAICompatibleAIProvider:
    """Connecteur HTTP UNIQUE pour tout fournisseur exposant un endpoint
    "chat/completions" compatible OpenAI (DeepSeek, Kimi/Moonshot AI, ou
    tout autre service equivalent) — jamais une implementation separee
    par fournisseur, la forme de requete/reponse etant identique.

    `base_url`/`api_key`/`model` proviennent EXCLUSIVEMENT de
    `settings.AI_PROVIDER_CONFIG` (cf. `get_ai_provider`), jamais d'une
    valeur codee en dur ici. N'est JAMAIS instanciee par defaut."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
        """POST `{base_url}/chat/completions` avec un corps JSON de forme
        OpenAI standard (`model`/`messages`/`max_tokens`) — `requests` deja
        une dependance de ce depot (cf. `apps.purchase.services.
        price_watch.GenericHttpPriceSourceProvider`), jamais un nouveau
        client HTTP ajoute pour ce seul besoin. Toute erreur reseau/HTTP/de
        forme de reponse est journalisee et relevee comme `AIProviderError`
        — jamais une exception brute `requests`/JSON qui surprendrait
        l'appelant (seule difference avec `GenericHttpPriceSourceProvider`,
        qui degrade en `PriceQuote` plutot que de lever : ici l'appelant
        metier, `apps.projects.services.ai_assistant`, est celui qui
        decide de la degradation, pas ce connecteur generique)."""
        import requests

        url = f"{self.base_url}/chat/completions"
        try:
            response = requests.post(
                url,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            return str(content)
        except requests.RequestException as exc:
            logger.warning("Echec reseau du connecteur IA (%s) : %s", self.base_url, exc)
            raise AIProviderError(str(exc)) from exc
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("Reponse inattendue du connecteur IA (%s) : %s", self.base_url, exc)
            raise AIProviderError(str(exc)) from exc

    def complete_with_tools(
        self, messages: list[dict[str, Any]], tools: list[ToolDefinition], *, max_tokens: int = 500
    ) -> ToolCallResult:
        """POST `{base_url}/chat/completions` avec le corps JSON standard
        "tool calling" compatible OpenAI (`tools` en JSON Schema,
        `tool_choice="auto"` — le modele decide lui-meme d'appeler ou non
        un tool, jamais force) — deja supporte nativement par Ollama pour
        les modeles compatibles (`qwen2.5:7b`, deja choisi par defaut en
        AI8) ainsi que DeepSeek/Kimi cote cloud, meme connecteur reutilise
        sans modification de ses parametres de configuration (cf. docstring
        de module). `choices[0].message.tool_calls[].function.arguments`
        est une chaine JSON (forme standard du protocole) explicitement
        deserialisee ici en dict avant de construire chaque `ToolCall` —
        meme discipline d'erreurs que `complete()` : reseau/HTTP/forme de
        reponse inattendue -> `AIProviderError`, jamais une exception brute
        `requests`/JSON/`json.JSONDecodeError` qui surprendrait l'appelant."""
        import json

        import requests

        url = f"{self.base_url}/chat/completions"
        try:
            response = requests.post(
                url,
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool.parameters_schema,
                            },
                        }
                        for tool in tools
                    ],
                    "tool_choice": "auto",
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            content = message.get("content")
            raw_tool_calls = message.get("tool_calls") or []
            tool_calls = [
                ToolCall(
                    id=raw["id"],
                    name=raw["function"]["name"],
                    arguments=json.loads(raw["function"]["arguments"] or "{}"),
                )
                for raw in raw_tool_calls
            ]
            return ToolCallResult(content=content, tool_calls=tool_calls)
        except requests.RequestException as exc:
            logger.warning("Echec reseau du connecteur IA (%s) : %s", self.base_url, exc)
            raise AIProviderError(str(exc)) from exc
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.warning("Reponse inattendue du connecteur IA (%s) : %s", self.base_url, exc)
            raise AIProviderError(str(exc)) from exc


def get_ai_provider() -> AIProvider:
    """Retourne le provider actif : `StubAIProvider` par defaut (aucune
    configuration, ou `base_url`/`api_key` incomplets), un
    `OpenAICompatibleAIProvider` construit a partir de `settings.
    AI_PROVIDER_CONFIG` UNIQUEMENT si l'utilisateur a explicitement rempli
    ces deux cles. Ne resout jamais un connecteur "par convention" —
    silence radio de la configuration = stub, systematiquement (meme
    discipline que `apps.purchase.services.price_watch.
    get_provider_for_platform`)."""
    from django.conf import settings

    config = getattr(settings, "AI_PROVIDER_CONFIG", {}) or {}
    base_url = config.get("base_url")
    api_key = config.get("api_key")
    if not base_url or not api_key:
        return StubAIProvider()

    model = config.get("model") or _DEFAULT_MODEL
    return OpenAICompatibleAIProvider(base_url=base_url, api_key=api_key, model=model)
