from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.db.uuid7 import uuid7


class AuditLog(models.Model):
    """Journal d'audit transversal du socle — trace TOUTE operation
    significative de l'application (creation/modification/suppression,
    connexions, exports, transitions de workflow, acces a des donnees
    personnelles...), pas seulement les acces RGPD (qui en sont un cas
    d'usage parmi d'autres, via `action="pii_access"`).

    Immuable au niveau base de donnees par un trigger Postgres qui rejette
    tout UPDATE/DELETE (cf. migration 0002_audit_log_immutable et
    `apps/core/management/commands/apply_rls.py` pour le mecanisme
    equivalent applique a la RLS) — efficace meme pour le proprietaire de
    la table, contrairement a un simple REVOKE de privileges."""

    ACTION_CREATED = "created"
    ACTION_UPDATED = "updated"
    ACTION_DELETED = "deleted"
    ACTION_LOGIN = "login"
    ACTION_LOGIN_FAILED = "login_failed"
    ACTION_PII_ACCESS = "pii_access"
    ACTION_EXPORT = "export"
    ACTION_PERMISSION_CHANGE = "permission_change"
    ACTION_OTHER = "other"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=32, db_index=True)

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_audit_log"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at}"
