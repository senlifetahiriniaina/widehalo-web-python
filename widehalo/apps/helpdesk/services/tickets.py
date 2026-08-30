"""Services metier `helpdesk` (HD1) : creation de ticket, transitions FSM
(chacune appelle `attempt_transition()` PUIS `instance.save(update_fields=
[...])` explicitement — garde-fou AST `tests/architecture/
test_attempt_transition_saves_state.py`), commentaires."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.helpdesk.models import (
    KIND_DEMANDE,
    PRIORITY_NORMAL,
    HlpTeam,
    HlpTicket,
    HlpTicketComment,
    HlpTicketTypeCatalog,
)


def create_ticket(
    tenant: Tenant,
    *,
    subject: str,
    requester: User,
    kind: str = KIND_DEMANDE,
    description: str = "",
    ticket_type: HlpTicketTypeCatalog | None = None,
    priority: str = "",
    assignee: User | None = None,
    team: HlpTeam | None = None,
    content_object: Any | None = None,
    blocks_operations: bool = False,
    created_by: User | None = None,
) -> HlpTicket:
    """Cree un ticket. `priority`/`team` sont pre-remplis depuis
    `ticket_type.default_priority`/`default_team` quand le type de ticket en
    porte un et qu'aucune valeur explicite n'est fournie par l'appelant —
    l'appelant garde toujours le dernier mot."""
    resolved_priority = priority
    resolved_team = team
    if ticket_type is not None:
        if not resolved_priority and ticket_type.default_priority:
            resolved_priority = ticket_type.default_priority
        if resolved_team is None and ticket_type.default_team_id:
            resolved_team = ticket_type.default_team
    if not resolved_priority:
        resolved_priority = PRIORITY_NORMAL

    reference = next_reference(tenant, HlpTicket.SEQUENCE_CODE, timezone.now().year)

    ticket = HlpTicket(
        tenant=tenant,
        reference=reference,
        subject=subject,
        description=description,
        kind=kind,
        ticket_type=ticket_type,
        priority=resolved_priority,
        requester=requester,
        assignee=assignee,
        team=resolved_team,
        blocks_operations=blocks_operations,
        created_by=created_by,
    )
    if content_object is not None:
        ticket.content_type = ContentType.objects.get_for_model(content_object.__class__)
        ticket.object_id = str(content_object.pk)
    ticket.save()
    return ticket


def assign_ticket(ticket: HlpTicket, user: User, *, assignee: User | None = None) -> HlpTicket:
    if assignee is not None:
        ticket.assignee = assignee
    attempt_transition(ticket, "assign", user)
    # Liste litterale (pas une liste construite dynamiquement) : requis par
    # le garde-fou AST `tests/architecture/test_attempt_transition_saves_
    # state.py`, qui ne peut prouver la presence du champ FSM que dans un
    # `update_fields=[...]` litteral. `assignee` est donc TOUJOURS inclus
    # (ecriture idempotente : `None` ne change rien s'il n'a pas ete
    # modifie ci-dessus).
    ticket.save(update_fields=["state", "assignee"])
    return ticket


def request_more_info(ticket: HlpTicket, user: User) -> HlpTicket:
    attempt_transition(ticket, "request_more_info", user)
    ticket.save(update_fields=["state"])
    return ticket


def resume_ticket(ticket: HlpTicket, user: User) -> HlpTicket:
    attempt_transition(ticket, "resume", user)
    ticket.save(update_fields=["state"])
    return ticket


def resolve_ticket(ticket: HlpTicket, user: User) -> HlpTicket:
    attempt_transition(ticket, "resolve", user)
    ticket.resolved_at = timezone.now()
    ticket.save(update_fields=["state", "resolved_at"])
    return ticket


def reopen_ticket(ticket: HlpTicket, user: User) -> HlpTicket:
    attempt_transition(ticket, "reopen", user)
    ticket.resolved_at = None
    ticket.closed_at = None
    ticket.save(update_fields=["state", "resolved_at", "closed_at"])
    return ticket


def close_ticket(ticket: HlpTicket, user: User) -> HlpTicket:
    attempt_transition(ticket, "close", user)
    ticket.closed_at = timezone.now()
    ticket.save(update_fields=["state", "closed_at"])
    return ticket


def escalate_ticket(ticket: HlpTicket, user: User, *, reason: str = "") -> HlpTicket:
    """Escalade manuelle (HD1) — l'integration automatique avec
    `HlpEscalationRule`/le calcul de `risk_score` arrive en HD2 (cf.
    docstring de `models.py`). `reason` n'est pas encore persiste (pas de
    `HlpEscalationEvent` avant HD2) : parametre deja present dans la
    signature pour que l'API HD1 n'ait pas a changer de forme en HD2."""
    attempt_transition(ticket, "escalate", user)
    ticket.save(update_fields=["state"])
    return ticket


def cancel_ticket(ticket: HlpTicket, user: User) -> HlpTicket:
    attempt_transition(ticket, "cancel", user)
    ticket.save(update_fields=["state"])
    return ticket


def add_comment(
    ticket: HlpTicket,
    *,
    author: User | None,
    body: str,
    is_internal_note: bool = False,
    attachment: Any | None = None,
) -> HlpTicketComment:
    """Ajoute un commentaire au fil du ticket. Positionne
    `HlpTicket.first_responded_at` au premier commentaire NON interne
    provenant de quelqu'un d'AUTRE que le demandeur — c'est la definition
    la plus fidele d'une "premiere reponse" sans encore aucune politique
    SLA (HD2) pour la piloter."""
    comment = HlpTicketComment.objects.create(
        tenant=ticket.tenant,
        ticket=ticket,
        author=author,
        body=body,
        is_internal_note=is_internal_note,
        attachment=attachment,
    )
    if (
        not is_internal_note
        and ticket.first_responded_at is None
        and author is not None
        and author_id_differs_from_requester(ticket, author)
    ):
        ticket.first_responded_at = timezone.now()
        ticket.save(update_fields=["first_responded_at"])
    return comment


def author_id_differs_from_requester(ticket: HlpTicket, author: User) -> bool:
    return ticket.requester_id != author.id


def user_can_manage_ticket(ticket: HlpTicket, user: User) -> bool:
    """Scope N3 (RBAC, cf. plan section dediee) : un utilisateur sans
    `helpdesk.change_hlpticket` peut neanmoins transitionner/commenter un
    ticket dont il est `requester` OU `assignee` — jamais celui d'un tiers.
    Meme patron que `apps.strategy.services.scoping.
    scope_objectives_for_user`/`apps.crm.services.scoping`, applique ici au
    niveau enregistrement (pas au niveau queryset, HD1 n'a pas encore
    d'ecran "mes tickets" filtre) — verifie explicitement dans
    `apps.helpdesk.api` a chaque endpoint de mutation/transition/
    commentaire."""
    if user.has_perm("helpdesk.change_hlpticket"):
        return True
    return ticket.requester_id == user.id or ticket.assignee_id == user.id
