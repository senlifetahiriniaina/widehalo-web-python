"""ETag/If-Match generique pour les PATCH critiques (evite les ecrasements
concurrents silencieux). Calcule a partir de `updated_at` de l'objet, pas
du contenu complet (suffisant pour BaseModel qui a toujours ce champ)."""

from __future__ import annotations

import hashlib
from typing import Any

from django.http import HttpRequest


def compute_etag(obj: Any) -> str:
    updated_at = getattr(obj, "updated_at", None)
    raw = f"{obj.pk}:{updated_at.isoformat() if updated_at else ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check_if_match(request: HttpRequest, obj: Any) -> bool:
    """Renvoie False si un If-Match est fourni et ne correspond pas a
    l'ETag courant de l'objet (l'appelant doit alors repondre 412)."""
    if_match: str | None = request.headers.get("If-Match")
    if not if_match:
        return True
    return if_match.strip('"') == compute_etag(obj)
