"""Recherche globale — tsvector fr/en + pg_trgm, filtree par tenant et par
permission RBAC (cf. services/search.py)."""

from ninja import Router

from apps.core.context import get_current_tenant_id
from apps.core.services.search import global_search

router = Router(tags=["search"])


@router.get("/search")
def search(request, q: str = ""):
    results = global_search(q, user=request.auth, tenant_id=get_current_tenant_id())
    return {
        "query": q,
        "results": [
            {"reference": r.reference, "text": r.text, "url": r.url, "content_type": r.content_type}
            for r in results
        ],
    }
