from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.db.uuid7 import uuid7


class Tenant(models.Model):
    """Une societe/tenant. Racine de l'isolation multi-tenant (discriminant
    + Row-Level Security PostgreSQL, cf. apps/core/models/base.py)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(_("raison sociale"), max_length=255)
    nif = models.CharField(_("NIF"), max_length=32, blank=True)
    country_code = models.CharField(max_length=2, default="MG")
    base_currency = models.CharField(max_length=3, default="MGA")
    default_language = models.CharField(max_length=5, default="fr")
    timezone = models.CharField(max_length=64, default="Indian/Antananarivo")
    retention_policy = models.JSONField(default=dict, blank=True)

    is_sandbox = models.BooleanField(default=False)
    sandbox_source = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="sandboxes"
    )
    sandbox_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_tenant"
        verbose_name = _("société")
        verbose_name_plural = _("sociétés")

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def soft_delete(self) -> None:
        from django.utils import timezone as tz

        self.is_active = False
        self.archived_at = tz.now()
        self.save(update_fields=["is_active", "archived_at"])
