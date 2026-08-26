"""Registre des sources de recherche — un futur module metier declare
comment transformer une de ses instances en entree de recherche globale,
sans que `core` ait besoin de connaitre ce module (respect de la regle de
couplage n°1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict


class SearchPayload(TypedDict):
    reference: str
    text: str
    url: str


Extractor = Callable[[Any], SearchPayload]

_REGISTRY: dict[type, Extractor] = {}


def register_search_source(model: type) -> Callable[[Extractor], Extractor]:
    def decorator(extractor: Extractor) -> Extractor:
        _REGISTRY[model] = extractor
        return extractor

    return decorator


def get_extractor(model: type) -> Extractor | None:
    return _REGISTRY.get(model)


def registered_models() -> list[type]:
    return list(_REGISTRY.keys())
