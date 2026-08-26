from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class EventLog(models.Model):
    """Persistance de tout evenement publie sur le bus interne — permet le
    rejeu (`replay_events`) meme si le dispatch echoue apres coup. Seul
    canal de communication asynchrone autorise entre modules (regle de
    couplage n°5)."""

    STATUS_PENDING = "pending"
    STATUS_DISPATCHED = "dispatched"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_DISPATCHED, "Distribué"),
        (STATUS_FAILED, "Échoué"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(null=True, blank=True)
    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_event_log"

    def __str__(self) -> str:
        return f"{self.event_type} ({self.status})"
