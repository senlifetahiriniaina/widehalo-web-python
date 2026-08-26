from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.search import SearchQuery, SearchVector, TrigramSimilarity
from django.db.models import Value
from django.db.models.functions import Greatest

from apps.core.models.search import SearchDocument
from apps.core.models.user import User
from apps.core.services.search_registry import get_extractor


def index_object(instance: Any, *, tenant_id: str) -> SearchDocument:
    """(Re)construit l'entree de recherche d'un objet — a appeler depuis le
    module metier proprietaire (ou son abonnement a `search.reindex_requested`
    sur le bus d'evenements) apres chaque creation/modification."""
    extractor = get_extractor(instance.__class__)
    if extractor is None:
        raise ValueError(f"Aucune source de recherche enregistree pour {instance.__class__}")

    payload = extractor(instance)
    content_type = ContentType.objects.get_for_model(instance.__class__)

    doc, _created = SearchDocument.objects.update_or_create(
        content_type=content_type,
        object_id=str(instance.pk),
        defaults={
            "tenant_id": tenant_id,
            "reference": payload["reference"],
            "text": payload["text"],
            "url": payload["url"],
        },
    )
    SearchDocument.objects.filter(pk=doc.pk).update(
        search_vector=(
            SearchVector("text", config="french") + SearchVector("text", config="english")
        )
    )
    return doc


def remove_from_index(instance: Any) -> None:
    content_type = ContentType.objects.get_for_model(instance.__class__)
    SearchDocument.objects.filter(content_type=content_type, object_id=str(instance.pk)).delete()


@dataclass
class SearchResult:
    reference: str
    text: str
    url: str
    content_type: str


def global_search(query: str, *, user: User, tenant_id: str, limit: int = 20) -> list[SearchResult]:
    """Recherche filtree par tenant ET par permission RBAC (l'utilisateur
    doit avoir `view_<model>` sur le content-type de chaque resultat) —
    reference exacte prioritaire, puis pertinence tsvector, puis similarite
    (tolerance aux fautes de frappe via pg_trgm)."""
    if not query:
        return []

    search_query = SearchQuery(query, config="french") | SearchQuery(query, config="english")

    queryset = (
        SearchDocument.objects.filter(tenant_id=tenant_id)
        .annotate(
            rank=Greatest(
                TrigramSimilarity("text", query),
                Value(0.0),
            )
        )
        .filter(search_vector=search_query)
        .order_by("-rank")[: limit * 3]
    )

    results = []
    for doc in queryset:
        model = doc.content_type.model_class()
        if model is None:
            continue
        permission_codename = f"{doc.content_type.app_label}.view_{doc.content_type.model}"
        if not user.has_perm(permission_codename):
            continue
        results.append(
            SearchResult(
                reference=doc.reference,
                text=doc.text,
                url=doc.url,
                content_type=doc.content_type.model,
            )
        )
        if len(results) >= limit:
            break

    results.sort(key=lambda r: r.reference.lower() != query.lower())
    return results
