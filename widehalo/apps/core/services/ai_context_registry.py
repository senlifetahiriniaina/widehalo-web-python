"""Registre central de la guidance contextuelle IA (module `ai`, chantier
« Assistant contextuel par page ») — meme patron que `apps.core.services.
reports_registry`/`automation_registry` : chaque module metier s'auto-
enregistre via son propre `apps.py::ready()`, jamais un import direct par
`apps.ai` d'un service d'un autre module (regle de couplage n1 — `ai` ne
declare de dependance que sur `core`).

Un module enregistre une guidance STATIQUE fr/en (le texte de repli garanti,
jamais d'erreur si aucun fournisseur IA reel n'est configure ou si le budget
de tokens du tenant est epuise, cf. `apps.ai.services.usage_budget`) et,
optionnellement, un `context_builder` — une fonction qui enrichit le prompt
envoye au LLM avec des DONNEES REELLES du tenant (jamais un contexte
invente). Le registre est un simple dictionnaire en memoire, peuple une
fois au demarrage de Django (comme `core.events._HANDLERS`) — jamais
reinitialise en cours de vie du process."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Un context builder recoit le tenant_id et renvoie un dict serialisable
# (jamais un objet ORM) qui sera injecte dans le prompt envoye au LLM —
# aucune garantie de forme au-dela d'etre du JSON valide, chaque module
# documente lui-meme les cles qu'il produit.
ContextBuilder = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredContext:
    module: str
    static_guidance_fr: str
    static_guidance_en: str
    context_builder: ContextBuilder | None = None


_REGISTRY: dict[str, RegisteredContext] = {}


def register_context(
    module: str,
    *,
    static_guidance_fr: str,
    static_guidance_en: str,
    context_builder: ContextBuilder | None = None,
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `module` re-enregistre remplace simplement l'entree — utile en
    reload de dev)."""
    _REGISTRY[module] = RegisteredContext(
        module=module,
        static_guidance_fr=static_guidance_fr,
        static_guidance_en=static_guidance_en,
        context_builder=context_builder,
    )


def get_context(module: str) -> RegisteredContext | None:
    return _REGISTRY.get(module)


def list_registered_contexts() -> list[RegisteredContext]:
    return sorted(_REGISTRY.values(), key=lambda c: c.module)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
