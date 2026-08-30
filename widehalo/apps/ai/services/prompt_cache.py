"""AI6 — Cache de prompts (formalisation du mecanisme deja construit ad hoc
en AI2, cf. `apps.ai.services.contextual_assistant`). Point d'entree :
`build_cache_key`/`build_prompt_cache_key`/`hash_payload`/`get_cached`/
`set_cached`.

Wrapper mince autour de `django.core.cache.cache` (backend Redis deja en
place, meme idiome que `apps.core.throttling`) — ne fait qu'encapsuler
`cache.get`/`cache.set` avec un TTL par defaut et deux constructeurs de cle
uniformes, pour que toute future fonctionnalite IA (AI7 et au-dela) n'ait
jamais a reinventer sa propre convention de cle/son propre hachage.

**Renommage assume (cf. plan)** : pas de service nomme `AnthropicCacheService`
(spec Laravel source, `cache_control: ephemeral` propriétaire Anthropic) —
mecanisme neutre vis-a-vis du fournisseur, coherent avec la cible
DeepSeek/Kimi/local de ce chantier : un cache applicatif Redis generique est
en realite PLUS largement applicable que l'en-tete propriétaire qu'il
remplace, quel que soit le fournisseur configure derriere
`apps.core.services.ai_assistant.get_ai_provider()`.

Refactor sans changement de comportement : `apps.ai.services.
contextual_assistant` (AI2) est le seul consommateur reel a ce jour — il
appelait deja `django.core.cache.cache` directement avec la meme cle
`ai_assist:{module}:{action}:{locale}:{role_code}:{context_hash}` et le meme
TTL 300s ; ce module ne fait qu'extraire ce mecanisme deja existant, jamais
en modifier la forme (un hit deja valide avant ce refactor reste un hit
apres). AI3 (narrative d'anomalie), AI4 (extraction de filtres NL) et AI5
(insights) ne mettent volontairement RIEN en cache : chacun est un calcul
par execution/par requete rarement repetee a l'identique (une narrative
d'anomalie est generee une seule fois a la creation de l'anomalie, une
recherche NL varie par construction, un run d'insights est periodique) — un
cache n'y apporterait aucun gain, disclosed ici plutot que suppose."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.cache import cache

DEFAULT_TTL_SECONDS = 300


def build_cache_key(feature: str, *parts: str) -> str:
    """Cle lisible `feature:part1:part2:...` — usage attendu : chaque partie
    est deja courte et discriminante (ex. module/action/locale/role_code),
    meme forme que la cle historique d'AI2."""
    return ":".join([feature, *parts])


def hash_payload(payload: dict[str, Any]) -> str:
    """Hache un payload JSON-serialisable (ex. contexte tenant) en une
    empreinte courte et stable — extrait de l'ancien `_context_hash` d'AI2,
    reutilisable par toute future fonctionnalite qui doit distinguer un
    cache par contenu de contexte plutot que par sa seule presence/absence."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def build_prompt_cache_key(feature: str, model: str, prompt: str) -> str:
    """Cle pour un cache de PROMPT LLM brut (feature+modele+prompt) — utile
    a une future fonctionnalite qui mettrait en cache directement une paire
    prompt/completion plutot qu'une reponse structuree par contexte metier
    (cas d'usage d'AI2, cf. `build_cache_key`). Non consommee par AI2-AI5,
    posee ici pour AI7+ sans reinvention future."""
    digest = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()[:24]
    return f"{feature}:{digest}"


def get_cached(key: str) -> Any | None:
    """Renvoie la valeur en cache pour `key`, ou `None` si absente/expiree —
    jamais d'exception (comportement natif de `cache.get`, deja tolerant)."""
    return cache.get(key)


def set_cached(key: str, value: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    """Ecrit `value` en cache sous `key` avec un TTL explicite (300s par
    defaut, meme valeur que le mecanisme historique d'AI2)."""
    cache.set(key, value, timeout=ttl_seconds)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "build_cache_key",
    "build_prompt_cache_key",
    "get_cached",
    "hash_payload",
    "set_cached",
]
