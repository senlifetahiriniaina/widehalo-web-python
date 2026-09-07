from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.db.uuid7 import uuid7
from apps.core.models.base import BaseModel


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


class ApprovalRule(BaseModel):
    """Regle d'approbation generique, applicable a n'importe quel modele
    metier futur via content-type — le socle ne connait pas les modeles
    concrets qui l'utiliseront.

    **Passee sous `BaseModel`, donc sous Row-Level Security.** Elle portait
    depuis toujours une vraie cle etrangere `tenant` non nulle : rien
    n'empechait cet heritage, sinon qu'elle est anterieure a la discipline.
    `id` et `is_active` etaient IDENTIQUES a ceux de `BaseModel` — les
    supprimer ne change rien en base. Seul `on_delete` bouge, de CASCADE a
    PROTECT, et c'est une correction : supprimer une societe qui a des
    regles de validation actives ne doit pas les emporter en silence. Les
    chemins de purge (`services/sandbox.py`, `services/tenant_reset.py`)
    parcourent deja tous les `BaseModel` — la regle y entre donc
    automatiquement, au lieu d'etre effacee par la cascade sans passer par
    eux."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    condition = models.JSONField(default=dict, blank=True)
    approver_role = models.CharField(max_length=32, blank=True)
    sequence_order = models.PositiveSmallIntegerField(default=1)

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


class ApprovalRequest(BaseModel):
    """Demande de validation d'une piece, contre une regle.

    **Elle n'avait AUCUNE colonne de societe.** Son rattachement passait
    uniquement par `rule.tenant_id` — une jointure, donc quelque chose
    qu'une requete peut oublier. C'est exactement ce qui s'etait produit :
    `pending_for_user` ne filtrait sur rien, et un validateur voyait les
    demandes de toutes les societes de l'instance.

    Le filtre de service a corrige la fuite ; cet heritage pose le filet en
    dessous. La colonne `tenant` est desormais portee par la ligne
    elle-meme, la Row-Level Security s'applique, et une requete qui
    oublierait le filtre ne renvoie plus rien au lieu de tout renvoyer.

    `tenant` et `rule.tenant` doivent toujours coincider — c'est
    `services/approvals.py::request_approval` qui l'etablit, et la lecture
    verifie les deux, si bien qu'une divergence rendrait la demande
    invisible plutot que visible a tort."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvée"),
        (STATUS_REJECTED, "Rejetée"),
    ]

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
