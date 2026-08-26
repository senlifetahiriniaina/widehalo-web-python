"""Squelette de recherche globale — implementation complete a l'etape 11
(tsvector fr/en + pg_trgm, register_search_source())."""

from __future__ import annotations

from ninja import Router

router = Router(tags=["search"])


@router.get("/search")
def search(request, q: str = ""):
    return {"query": q, "results": []}
