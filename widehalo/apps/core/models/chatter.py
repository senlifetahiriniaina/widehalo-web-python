from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models.base import BaseModel


class ChatterMessage(BaseModel):
    """Fil de discussion generique attache a n'importe quel objet metier
    (facon "chatter" Odoo — A.7/A.11 du cahier des charges refonte UX,
    Sprint 3 / L2, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
    messages ET notes internes sur le meme fil, distingues par `is_note`.

    Distinct de `apps.chat` (messagerie interne temps reel par canal,
    WebSocket) : ce modele est un historique attache a UN enregistrement
    metier (devis, commande, dossier...), pas une conversation entre
    utilisateurs — meme convention GenericForeignKey que `AuditLog`
    (`apps/core/models/audit.py`), pour rester coherent avec l'unique
    autre "timeline" deja existante du depot plutot que d'en inventer une
    troisieme."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    author = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()
    is_note = models.BooleanField(
        default=False,
        help_text="Note interne (jamais visible du tiers/client) vs message.",
    )

    class Meta:
        db_table = "core_chatter_message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        kind = "note" if self.is_note else "message"
        return f"{kind} @ {self.created_at}"
