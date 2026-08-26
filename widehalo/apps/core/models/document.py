from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models.base import BaseModel


class Document(BaseModel):
    """Document polymorphe (rattachable a n'importe quel objet metier futur
    via content-type), stocke via l'API `Storage` abstraite de Django
    (`settings.STORAGES["default"]`) — jamais de chemin disque en dur dans
    le code applicatif, pour permettre une bascule future vers S3/Hetzner
    Object Storage sans changement de code. Herite de BaseModel pour
    beneficier de la Row-Level Security au meme titre que le reste du
    socle."""

    SCAN_PENDING = "pending"
    SCAN_CLEAN = "clean"
    SCAN_INFECTED = "infected"
    SCAN_ERROR = "error"
    SCAN_CHOICES = [
        (SCAN_PENDING, "En attente"),
        (SCAN_CLEAN, "Propre"),
        (SCAN_INFECTED, "Infecté"),
        (SCAN_ERROR, "Erreur"),
    ]

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    file = models.FileField(upload_to="documents/%Y/%m/")
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=127, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    reference_count = models.PositiveIntegerField(default=1)

    av_scan_status = models.CharField(max_length=16, choices=SCAN_CHOICES, default=SCAN_PENDING)

    class Meta:
        db_table = "core_document"
        unique_together = ("tenant", "sha256")

    def __str__(self) -> str:
        return self.original_name
