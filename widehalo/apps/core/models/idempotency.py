from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class IdempotencyKey(models.Model):
    """Rejoue la reponse originale si un POST marque @idempotent est
    soumis a nouveau avec la meme cle (meme corps) — evite les doublons
    d'effet en cas de retransmission reseau (contrainte de connectivite
    malgache variable)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "core_idempotency_key"
        unique_together = ("tenant_id", "user_id", "key")

    def __str__(self) -> str:
        return f"{self.key} ({self.response_status})"
