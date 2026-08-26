from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.db.uuid7 import uuid7


class StateTransitionLog(models.Model):
    """Journal generique (par content-type) de toute transition de machine
    a etat, alimente automatiquement par le signal django_fsm.post_transition
    (cf. apps/core/workflows.py) — aucun module metier n'a besoin d'ecrire
    explicitement dans cette table."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    field_name = models.CharField(max_length=100)
    from_state = models.CharField(max_length=100)
    to_state = models.CharField(max_length=100)
    performed_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    was_refused = models.BooleanField(default=False)
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_state_transition"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.content_type}#{self.object_id}: {self.from_state} -> {self.to_state}"


class ApprovalRule(models.Model):
    """Regle d'approbation generique, applicable a n'importe quel modele
    metier futur via content-type — le socle ne connait pas les modeles
    concrets qui l'utiliseront."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    condition = models.JSONField(default=dict, blank=True)
    approver_role = models.CharField(max_length=32, blank=True)
    sequence_order = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    # Cascade de secours : si la demande reste en attente plus longtemps que
    # `escalate_after`, elle devient egalement visible aux roles de
    # `fallback_approver_role` (cf. services/approvals.py::pending_for_user).
    # La detection reelle d'*absence* d'un validateur (conges...) dependra du
    # futur module Presence/RH — ce mecanisme socle se limite a une
    # escalade temporelle, independante de ce module.
    escalate_after = models.DurationField(null=True, blank=True)
    fallback_approver_role = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "core_approval_rule"
        ordering = ["sequence_order"]

    def __str__(self) -> str:
        return self.name


class ApprovalRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvée"),
        (STATUS_REJECTED, "Rejetée"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    rule = models.ForeignKey(ApprovalRule, on_delete=models.CASCADE, related_name="requests")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_by = models.ForeignKey(
        "core.User", related_name="requested_approvals", on_delete=models.CASCADE
    )
    decided_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        related_name="decided_approvals",
        on_delete=models.SET_NULL,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_approval_request"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.rule} — {self.status}"


class ApprovalDelegation(models.Model):
    """Delegation temporaire de validation entre deux utilisateurs."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    delegator = models.ForeignKey(
        "core.User", related_name="delegations_given", on_delete=models.CASCADE
    )
    delegate = models.ForeignKey(
        "core.User", related_name="delegations_received", on_delete=models.CASCADE
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    scope = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "core_approval_delegation"

    def __str__(self) -> str:
        return f"{self.delegator} -> {self.delegate}"
