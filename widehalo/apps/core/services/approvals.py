from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import DateTimeField, ExpressionWrapper, F, Q, QuerySet
from django.utils import timezone

from apps.core.models.user import User
from apps.core.models.workflow import ApprovalDelegation, ApprovalRequest, ApprovalRule


def request_approval(
    obj: Any, rule: ApprovalRule, requested_by: User, comment: str = ""
) -> ApprovalRequest:
    return ApprovalRequest.objects.create(
        rule=rule,
        content_type=ContentType.objects.get_for_model(obj.__class__),
        object_id=str(obj.pk),
        requested_by=requested_by,
        comment=comment,
    )


def _delegate_ids_for(user: User) -> list[Any]:
    now = timezone.now()
    return list(
        ApprovalDelegation.objects.filter(
            delegate=user, valid_from__lte=now, valid_to__gte=now
        ).values_list("delegator_id", flat=True)
    )


def pending_for_user(user: User) -> QuerySet[ApprovalRequest]:
    """Demandes en attente adressees a l'utilisateur : celles ou son role
    est l'approbateur principal, celles deleguees vers lui (delegation
    explicite), et celles escaladees vers son role de secours faute de
    decision dans le delai `rule.escalate_after` (cascade de validateurs
    de secours — l'absence reelle d'un validateur, elle, sera detectee
    plus tard par le futur module Presence/RH ; ici l'escalade est
    purement temporelle)."""
    delegator_ids = _delegate_ids_for(user)
    approver_roles = set(user.groups.values_list("name", flat=True))

    qs = ApprovalRequest.objects.annotate(
        escalates_at=ExpressionWrapper(
            F("created_at") + F("rule__escalate_after"), output_field=DateTimeField()
        )
    )
    return qs.filter(
        Q(status=ApprovalRequest.STATUS_PENDING)
        & (
            Q(rule__approver_role__in=approver_roles)
            | Q(requested_by_id__in=delegator_ids)
            | (
                Q(rule__fallback_approver_role__in=approver_roles)
                & Q(rule__escalate_after__isnull=False)
                & Q(escalates_at__lte=timezone.now())
            )
        )
    )


def decide(
    request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> ApprovalRequest:
    request.status = (
        ApprovalRequest.STATUS_APPROVED if approved else ApprovalRequest.STATUS_REJECTED
    )
    request.decided_by = decided_by
    request.decided_at = timezone.now()
    request.comment = comment
    request.save(update_fields=["status", "decided_by", "decided_at", "comment"])
    return request


def delegate_approval(
    delegator: User, delegate: User, valid_from: Any, valid_to: Any, scope: str = ""
) -> ApprovalDelegation:
    return ApprovalDelegation.objects.create(
        delegator=delegator,
        delegate=delegate,
        valid_from=valid_from,
        valid_to=valid_to,
        scope=scope,
    )
