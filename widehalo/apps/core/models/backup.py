"""Sauvegarde/restauration/reinitialisation en libre-service d'un tenant
(chantier « sauvegarde/restauration en libre-service, planification des
sauvegardes, reinitialisation des donnees d'une entreprise »). Economie de
modeles (2 nouveaux, meme discipline que `MrpBomLineState`/
`CatalogSectorSpec`...) :

- `TenantBackupSchedule` : configuration de planification, un enregistrement
  par tenant (contrainte d'unicite).
- `TenantDataOperation` : journal UNIQUE couvrant les 3 operations
  (`backup`/`restore`/`reset`) — le suivi detaille ligne-par-ligne des
  suppressions reste couvert automatiquement par `core_audit_log` (deja
  declenche par les signaux `post_delete` existants), jamais duplique ici."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel


class TenantBackupSchedule(BaseModel):
    """Configuration de sauvegarde planifiee — pas `ReferenceMixin` (config,
    jamais un document numerote). Un seul enregistrement par tenant."""

    FREQUENCY_DAILY = "daily"
    FREQUENCY_WEEKLY = "weekly"
    FREQUENCY_MONTHLY = "monthly"
    FREQUENCY_CHOICES = [
        (FREQUENCY_DAILY, _("Quotidienne")),
        (FREQUENCY_WEEKLY, _("Hebdomadaire")),
        (FREQUENCY_MONTHLY, _("Mensuelle")),
    ]

    frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES, default=FREQUENCY_DAILY)
    # `null=True` == "conserver toutes les sauvegardes" (pas de purge de
    # retention) — distinct de 0, qui n'aurait aucun sens metier (purger
    # une sauvegarde a peine creee).
    retention_count = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_tenant_backup_schedule"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_tenant_backup_schedule_tenant")
        ]

    def __str__(self) -> str:
        return f"Planification {self.tenant} ({self.frequency})"


class TenantDataOperation(BaseModel):
    """Journal unique des operations de sauvegarde/restauration/
    reinitialisation d'un tenant — pas `ReferenceMixin` (enregistrement de
    suivi, pas un document numerote, meme choix que `RiskItem`)."""

    TYPE_BACKUP = "backup"
    TYPE_RESTORE = "restore"
    TYPE_RESET = "reset"
    TYPE_CHOICES = [
        (TYPE_BACKUP, _("Sauvegarde")),
        (TYPE_RESTORE, _("Restauration")),
        (TYPE_RESET, _("Réinitialisation")),
    ]

    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, _("Succès")),
        (STATUS_FAILED, _("Échec")),
    ]

    TRIGGER_MANUAL = "manual"
    TRIGGER_SCHEDULED = "scheduled"
    TRIGGER_CHOICES = [
        (TRIGGER_MANUAL, _("Manuel")),
        (TRIGGER_SCHEDULED, _("Planifié")),
    ]

    operation_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_MANUAL)
    # Un document peut survivre/etre independant de l'operation qui l'a
    # produit (ex. archive telechargee puis reutilisee bien apres) — jamais
    # de cascade, SET_NULL. Renseigne pour un `backup`, et pour un
    # `restore` quand la source est une archive deja stockee.
    document = models.ForeignKey("core.Document", null=True, blank=True, on_delete=models.SET_NULL)
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    triggered_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = "core_tenant_data_operation"
        ordering = ["-created_at"]
        permissions = [("manage_tenant_backups", "Peut gérer les sauvegardes et restaurations")]

    def __str__(self) -> str:
        return f"{self.get_operation_type_display()} — {self.tenant} ({self.status})"
