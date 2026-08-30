"""API django-ninja du module `helpdesk` (HD1+HD2). CRUD `HlpTeam`/
`HlpTicketTypeCatalog` (admin/direction uniquement pour la creation/edition
du catalogue, lecture ouverte a tout role ayant acces au module), CRUD
`HlpTicket` + endpoints de transition FSM, creation de commentaires.

**HD2** : CRUD `HlpSlaPolicy`/`HlpEscalationRule` (permissions
PERSONNALISEES `helpdesk.manage_hlpslapolicy`/`manage_hlpescalationrule`,
admin/direction UNIQUEMENT — cf. section dediee plus bas), declenchement
manuel `/helpdesk/checks/run` (`helpdesk.run_helpdesk_checks`, memes
roles), historique d'escalade d'un ticket.

NOTE ordre des decorateurs (cf. `apps.core.services.permissions.
require_permission`) : `@router.xxx` DOIT rester le decorateur EXTERNE et
`@require_permission(...)` l'INTERNE (juste au-dessus de `def`).

**Scope N3** (cf. plan, section RBAC) : les endpoints de mutation/
transition/commentaire de `HlpTicket` acceptent aussi un utilisateur SANS
`helpdesk.change_hlpticket` des lors qu'il est `requester` OU `assignee`
du ticket cible (`services.tickets.user_can_manage_ticket`) — jamais celui
d'un tiers. Les endpoints de configuration (`HlpTeam`/
`HlpTicketTypeCatalog` en ecriture) restent `helpdesk.add_*`/
`helpdesk.change_*` stricts (admin/direction uniquement, cf.
`rbac_policy.ROLE_APP_PERMISSIONS`)."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import require_permission
from apps.core.services.workflow import TransitionPermissionError
from apps.helpdesk.models import (
    HlpEscalationEvent,
    HlpEscalationRule,
    HlpSlaPolicy,
    HlpTeam,
    HlpTicket,
    HlpTicketComment,
    HlpTicketTypeCatalog,
)
from apps.helpdesk.services import escalation, sla
from apps.helpdesk.services.tickets import (
    add_comment,
    assign_ticket,
    cancel_ticket,
    close_ticket,
    create_ticket,
    escalate_ticket,
    reopen_ticket,
    request_more_info,
    resolve_ticket,
    resume_ticket,
    user_can_manage_ticket,
)

router = Router(tags=["helpdesk"])


def _error_response(exc: Exception) -> JsonResponse:
    message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return JsonResponse({"detail": message}, status=400)


def _forbidden() -> JsonResponse:
    return JsonResponse({"detail": "permission refusée"}, status=403)


class TeamIn(Schema):
    name: str
    description: str = ""
    member_ids: list[str] = []


class TicketTypeIn(Schema):
    kind: str
    code: str
    label: str
    parent_id: str | None = None
    sector_code: str = ""
    related_module: str = ""
    default_team_id: str | None = None
    default_priority: str = ""


class TicketTypeUpdateIn(Schema):
    label: str | None = None
    sector_code: str | None = None
    related_module: str | None = None
    default_team_id: str | None = None
    default_priority: str | None = None
    is_active: bool | None = None


class TicketIn(Schema):
    subject: str
    description: str = ""
    kind: str
    ticket_type_id: str | None = None
    priority: str = ""
    assignee_id: str | None = None
    team_id: str | None = None
    sla_policy_id: str | None = None
    blocks_operations: bool = False


class SlaPolicyIn(Schema):
    name: str
    priority: str
    first_response_minutes: int
    resolution_minutes: int


class EscalationRuleIn(Schema):
    name: str
    condition_type: str
    threshold_minutes: int | None = None
    min_priority: str = ""
    escalate_to_team_id: str | None = None
    escalate_to_user_id: str | None = None


class CommentIn(Schema):
    body: str
    is_internal_note: bool = False


def _serialize_team(team: HlpTeam) -> dict[str, Any]:
    return {
        "id": str(team.id),
        "name": team.name,
        "description": team.description,
        "member_ids": [str(uid) for uid in team.members.values_list("id", flat=True)],
    }


def _serialize_ticket_type(entry: HlpTicketTypeCatalog) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "code": entry.code,
        "label": entry.label,
        "parent_id": str(entry.parent_id) if entry.parent_id else None,
        "sector_code": entry.sector_code,
        "related_module": entry.related_module,
        "related_content_type_id": entry.related_content_type_id,
        "default_team_id": str(entry.default_team_id) if entry.default_team_id else None,
        "default_priority": entry.default_priority,
        "is_active": entry.is_active,
    }


def _serialize_ticket(ticket: HlpTicket) -> dict[str, Any]:
    return {
        "id": str(ticket.id),
        "reference": ticket.reference,
        "subject": ticket.subject,
        "description": ticket.description,
        "kind": ticket.kind,
        "ticket_type_id": str(ticket.ticket_type_id) if ticket.ticket_type_id else None,
        "priority": ticket.priority,
        "state": ticket.state,
        "requester_id": str(ticket.requester_id),
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        "team_id": str(ticket.team_id) if ticket.team_id else None,
        "content_type_id": ticket.content_type_id,
        "object_id": ticket.object_id,
        "blocks_operations": ticket.blocks_operations,
        "sla_policy_id": str(ticket.sla_policy_id) if ticket.sla_policy_id else None,
        "first_response_due_at": ticket.first_response_due_at,
        "resolution_due_at": ticket.resolution_due_at,
        "first_responded_at": ticket.first_responded_at,
        "resolved_at": ticket.resolved_at,
        "closed_at": ticket.closed_at,
        "risk_score": ticket.risk_score,
    }


def _serialize_comment(comment: HlpTicketComment) -> dict[str, Any]:
    return {
        "id": str(comment.id),
        "ticket_id": str(comment.ticket_id),
        "author_id": str(comment.author_id) if comment.author_id else None,
        "body": comment.body,
        "is_internal_note": comment.is_internal_note,
        "created_at": comment.created_at,
    }


# --- HlpTeam -----------------------------------------------------------


@router.get("/helpdesk/teams")
@require_permission("helpdesk.view_hlpteam")
def list_teams_endpoint(request: Any) -> dict[str, Any]:
    teams = HlpTeam.objects.filter(is_active=True)
    return {"results": [_serialize_team(t) for t in teams]}


@router.post("/helpdesk/teams")
@require_permission("helpdesk.add_hlpteam")
def create_team_endpoint(request: Any, payload: TeamIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    team = HlpTeam.objects.create(
        tenant=tenant,
        name=payload.name,
        description=payload.description,
        created_by=request.auth,
    )
    if payload.member_ids:
        team.members.set(payload.member_ids)
    return _serialize_team(team)


# --- HlpTicketTypeCatalog ------------------------------------------------


@router.get("/helpdesk/ticket-types")
@require_permission("helpdesk.view_hlptickettypecatalog")
def list_ticket_types_endpoint(request: Any) -> dict[str, Any]:
    entries = HlpTicketTypeCatalog.objects.filter(is_active=True)
    return {"results": [_serialize_ticket_type(e) for e in entries]}


@router.get("/helpdesk/ticket-types/{entry_id}")
@require_permission("helpdesk.view_hlptickettypecatalog")
def get_ticket_type_endpoint(request: Any, entry_id: str) -> dict[str, Any]:
    entry = get_object_or_404(HlpTicketTypeCatalog, id=entry_id)
    return _serialize_ticket_type(entry)


@router.post("/helpdesk/ticket-types")
@require_permission("helpdesk.add_hlptickettypecatalog")
def create_ticket_type_endpoint(request: Any, payload: TicketTypeIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    entry = HlpTicketTypeCatalog.objects.create(
        tenant=tenant,
        kind=payload.kind,
        code=payload.code,
        label=payload.label,
        parent_id=payload.parent_id,
        sector_code=payload.sector_code,
        related_module=payload.related_module,
        default_team_id=payload.default_team_id,
        default_priority=payload.default_priority,
        created_by=request.auth,
    )
    return _serialize_ticket_type(entry)


@router.patch("/helpdesk/ticket-types/{entry_id}")
@require_permission("helpdesk.change_hlptickettypecatalog")
def update_ticket_type_endpoint(
    request: Any, entry_id: str, payload: TicketTypeUpdateIn
) -> dict[str, Any]:
    entry = get_object_or_404(HlpTicketTypeCatalog, id=entry_id)
    update_fields: list[str] = []
    for field in (
        "label",
        "sector_code",
        "related_module",
        "default_team_id",
        "default_priority",
        "is_active",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(entry, field, value)
            update_fields.append(field)
    if update_fields:
        entry.updated_by = request.auth
        entry.save(update_fields=[*update_fields, "updated_by"])
    return _serialize_ticket_type(entry)


# --- HlpTicket ------------------------------------------------------------


@router.get("/helpdesk/tickets")
@require_permission("helpdesk.view_hlpticket")
def list_tickets_endpoint(request: Any) -> dict[str, Any]:
    tickets = HlpTicket.objects.filter(is_active=True).order_by("-created_at")
    return {"results": [_serialize_ticket(t) for t in tickets]}


@router.post("/helpdesk/tickets")
@require_permission("helpdesk.add_hlpticket")
def create_ticket_endpoint(request: Any, payload: TicketIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    ticket_type = None
    if payload.ticket_type_id:
        ticket_type = get_object_or_404(HlpTicketTypeCatalog, id=payload.ticket_type_id)
    assignee = None
    if payload.assignee_id:
        assignee = get_object_or_404(User, id=payload.assignee_id)
    team = None
    if payload.team_id:
        team = get_object_or_404(HlpTeam, id=payload.team_id)
    sla_policy = None
    if payload.sla_policy_id:
        sla_policy = get_object_or_404(HlpSlaPolicy, id=payload.sla_policy_id)
    ticket = create_ticket(
        tenant,
        subject=payload.subject,
        description=payload.description,
        kind=payload.kind,
        ticket_type=ticket_type,
        priority=payload.priority,
        requester=request.auth,
        assignee=assignee,
        team=team,
        sla_policy=sla_policy,
        blocks_operations=payload.blocks_operations,
        created_by=request.auth,
    )
    return _serialize_ticket(ticket)


@router.get("/helpdesk/tickets/{ticket_id}")
@require_permission("helpdesk.view_hlpticket")
def get_ticket_endpoint(request: Any, ticket_id: str) -> dict[str, Any]:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    comments = [_serialize_comment(c) for c in ticket.comments.all()]
    return {**_serialize_ticket(ticket), "comments": comments}


def _handle_transition(fn: Any, ticket: HlpTicket, user: Any, **kwargs: Any) -> Any:
    try:
        return fn(ticket, user, **kwargs), None
    except (ValidationError, TransitionPermissionError) as exc:
        return None, _error_response(exc)


@router.post("/helpdesk/tickets/{ticket_id}/assign")
@require_permission("helpdesk.view_hlpticket")
def assign_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(assign_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/request-more-info")
@require_permission("helpdesk.view_hlpticket")
def request_more_info_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(request_more_info, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/resume")
@require_permission("helpdesk.view_hlpticket")
def resume_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(resume_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/resolve")
@require_permission("helpdesk.view_hlpticket")
def resolve_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(resolve_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/reopen")
@require_permission("helpdesk.view_hlpticket")
def reopen_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(reopen_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/close")
@require_permission("helpdesk.view_hlpticket")
def close_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(close_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/escalate")
@require_permission("helpdesk.view_hlpticket")
def escalate_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(escalate_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


@router.post("/helpdesk/tickets/{ticket_id}/cancel")
@require_permission("helpdesk.view_hlpticket")
def cancel_ticket_endpoint(request: Any, ticket_id: str) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    result, error = _handle_transition(cancel_ticket, ticket, request.auth)
    return error if error is not None else _serialize_ticket(result)


# --- HlpTicketComment -------------------------------------------------


@router.get("/helpdesk/tickets/{ticket_id}/comments")
@require_permission("helpdesk.view_hlpticket")
def list_comments_endpoint(request: Any, ticket_id: str) -> dict[str, Any]:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    return {"results": [_serialize_comment(c) for c in ticket.comments.all()]}


@router.post("/helpdesk/tickets/{ticket_id}/comments")
@require_permission("helpdesk.view_hlpticket")
def create_comment_endpoint(request: Any, ticket_id: str, payload: CommentIn) -> Any:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    if not user_can_manage_ticket(ticket, request.auth):
        return _forbidden()
    comment = add_comment(
        ticket,
        author=request.auth,
        body=payload.body,
        is_internal_note=payload.is_internal_note,
    )
    return _serialize_comment(comment)


@router.get("/helpdesk/tickets/{ticket_id}/escalation-history")
@require_permission("helpdesk.view_hlpticket")
def ticket_escalation_history_endpoint(request: Any, ticket_id: str) -> dict[str, Any]:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    events = ticket.escalation_events.all()
    return {"results": [_serialize_escalation_event(e) for e in events]}


# --- HlpSlaPolicy (HD2) -------------------------------------------------
#
# `helpdesk.manage_hlpslapolicy` (permission PERSONNALISEE, cf. `Meta.
# permissions` de `HlpSlaPolicy`) gate ICI lecture ET ecriture — cf.
# `apps.core.services.rbac_policy.CUSTOM_PERMISSIONS_MANAGE_HLP_ROLES`
# (admin/direction uniquement, meme discipline que `projects.
# manage_prjcustomfielddefinition`, PJ7). Les permissions auto-generees
# `helpdesk.view/add_hlpslapolicy` restent techniquement accordees plus
# largement par `ROLE_APP_PERMISSIONS["helpdesk"]` mais ne sont JAMAIS
# verifiees par ces endpoints.


def _serialize_sla_policy(policy: HlpSlaPolicy) -> dict[str, Any]:
    return {
        "id": str(policy.id),
        "name": policy.name,
        "priority": policy.priority,
        "first_response_minutes": policy.first_response_minutes,
        "resolution_minutes": policy.resolution_minutes,
    }


@router.get("/helpdesk/sla-policies")
@require_permission("helpdesk.manage_hlpslapolicy")
def list_sla_policies_endpoint(request: Any) -> dict[str, Any]:
    policies = HlpSlaPolicy.objects.filter(is_active=True)
    return {"results": [_serialize_sla_policy(p) for p in policies]}


@router.post("/helpdesk/sla-policies")
@require_permission("helpdesk.manage_hlpslapolicy")
def create_sla_policy_endpoint(request: Any, payload: SlaPolicyIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    policy = HlpSlaPolicy.objects.create(
        tenant=tenant,
        name=payload.name,
        priority=payload.priority,
        first_response_minutes=payload.first_response_minutes,
        resolution_minutes=payload.resolution_minutes,
        created_by=request.auth,
    )
    return _serialize_sla_policy(policy)


# --- HlpEscalationRule (HD2) --------------------------------------------
#
# Meme discipline RBAC que `HlpSlaPolicy` ci-dessus (`helpdesk.
# manage_hlpescalationrule`).


def _serialize_escalation_rule(rule: HlpEscalationRule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "condition_type": rule.condition_type,
        "threshold_minutes": rule.threshold_minutes,
        "min_priority": rule.min_priority,
        "escalate_to_team_id": str(rule.escalate_to_team_id) if rule.escalate_to_team_id else None,
        "escalate_to_user_id": str(rule.escalate_to_user_id) if rule.escalate_to_user_id else None,
        "is_active": rule.is_active,
    }


def _serialize_escalation_event(event: HlpEscalationEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "ticket_id": str(event.ticket_id),
        "rule_id": str(event.rule_id) if event.rule_id else None,
        "escalated_by_id": str(event.escalated_by_id) if event.escalated_by_id else None,
        "reason": event.reason,
        "created_at": event.created_at,
    }


@router.get("/helpdesk/escalation-rules")
@require_permission("helpdesk.manage_hlpescalationrule")
def list_escalation_rules_endpoint(request: Any) -> dict[str, Any]:
    rules = HlpEscalationRule.objects.filter(is_active=True)
    return {"results": [_serialize_escalation_rule(r) for r in rules]}


@router.post("/helpdesk/escalation-rules")
@require_permission("helpdesk.manage_hlpescalationrule")
def create_escalation_rule_endpoint(request: Any, payload: EscalationRuleIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rule = HlpEscalationRule.objects.create(
        tenant=tenant,
        name=payload.name,
        condition_type=payload.condition_type,
        threshold_minutes=payload.threshold_minutes,
        min_priority=payload.min_priority,
        escalate_to_team_id=payload.escalate_to_team_id,
        escalate_to_user_id=payload.escalate_to_user_id,
        created_by=request.auth,
    )
    return _serialize_escalation_rule(rule)


# --- Declenchement manuel des verifications SLA/escalade (HD2) ----------


@router.post("/helpdesk/checks/run")
@require_permission("helpdesk.run_helpdesk_checks")
def run_helpdesk_checks_endpoint(request: Any) -> dict[str, Any]:
    """Declenche `sla.check_breaches`/`escalation.run_escalation_checks`
    pour le tenant COURANT (utile pour tester/operer sans attendre le
    prochain passage de la commande de management `run_helpdesk_sla_checks`,
    cf. plan) — `admin`/`direction` uniquement (meme permission
    personnalisee que la configuration SLA/escalade)."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    breaches = sla.check_breaches(tenant)
    events = escalation.run_escalation_checks(tenant)
    return {
        "breaches_created": len(breaches),
        "escalations_created": len(events),
    }
