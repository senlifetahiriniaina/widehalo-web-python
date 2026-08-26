from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.core.db.uuid7 import uuid7


class SearchDocument(models.Model):
    """Index de recherche globale generique — un futur module metier
    s'enregistre via `register_search_source()`
    (cf. services/search_registry.py) au lieu d'implementer sa propre
    recherche. Une ligne par objet indexable, reconstruite a chaque
    sauvegarde de l'objet source (evenement `search.reindex_requested`)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    reference = models.CharField(max_length=100, blank=True, db_index=True)
    text = models.TextField()
    url = models.CharField(max_length=255, blank=True)

    search_vector = SearchVectorField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_search_document"
        indexes = [GinIndex(fields=["search_vector"])]
        unique_together = ("content_type", "object_id")

    def __str__(self) -> str:
        return self.reference or self.text[:50]
