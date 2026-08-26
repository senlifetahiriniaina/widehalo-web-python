from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.context import get_current_tenant_id
from apps.core.db.uuid7 import uuid7
from apps.core.models.user import User


class TenantManager(models.Manager["BaseModel"]):
    """Filtre systematiquement sur le tenant courant (contextvar alimentee
    par TenantMiddleware). Renvoie un queryset vide si aucun tenant n'est
    positionne (deny-by-default), jamais toutes les lignes de tous les
    tenants."""

    def get_queryset(self) -> models.QuerySet[BaseModel]:
        qs = super().get_queryset()
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            return qs.none()
        return qs.filter(tenant_id=tenant_id)


class BaseModel(models.Model):
    """Socle herite par toute entite metier. Garantit l'isolation tenant
    (cote applicatif via TenantManager, cote base via Row-Level Security —
    voir apps/core/management/commands/apply_rls.py), l'auditabilite et le
    soft-delete systematique."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.PROTECT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.SET_NULL,
    )

    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()
    all_objects = models.Manager["BaseModel"]()  # noqa: DJ012 (deuxieme manager volontaire)

    class Meta:
        abstract = True

    def soft_delete(self, by: User | None = None) -> None:
        self.is_active = False
        self.archived_at = timezone.now()
        if by is not None:
            self.updated_by = by
        self.save(update_fields=["is_active", "archived_at", "updated_by"])


class ReferenceMixin(models.Model):
    """Ajoute un champ `reference` sequence par tenant/exercice (cf.
    apps/core/services/sequences.py). A combiner avec BaseModel dans les
    entites metier qui exposent un numero de document (facture, commande,
    bulletin, etc.)."""

    reference = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        abstract = True
