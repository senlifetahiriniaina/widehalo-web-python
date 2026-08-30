"""Services metier `helpdesk` (HD1+HD2) : creation de ticket, transitions
FSM (chacune appelle `attempt_transition()` PUIS `instance.save(
update_fields=[...])` explicitement — garde-fou AST `tests/architecture/
test_attempt_transition_saves_state.py`), commentaires.

**HD2** : `create_ticket` resout desormais aussi `sla_policy` (meme chaine
de resolution exacte que `priority`/`team`, cf. sa docstring) et calcule
`first_response_due_at`/`resolution_due_at` quand une politique est
resolue ; `escalate_ticket` persiste desormais un `HlpEscalationEvent`
manuel et publie `"helpdesk.ticket_escalated"`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.core.events import publish_event
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.helpdesk.models import (
    KIND_DEMANDE,
    PRIORITY_NORMAL,
    HlpEscalationEvent,
    HlpSlaPolicy,
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
    sla_policy: HlpSlaPolicy | None = None,
    content_object: Any | None = None,
    blocks_operations: bool = False,
    created_by: User | None = None,
) -> HlpTicket:
    """Cree un ticket. `priority`/`team`/`sla_policy` sont pre-remplis
    depuis `ticket_type.default_priority`/`default_team`/`default_sla_policy`
    quand le type de ticket en porte un et qu'aucune valeur explicite n'est
    fournie par l'appelant — l'appelant garde toujours le dernier mot.

    **HD2** : si aucune `sla_policy` n'est resolue par les deux moyens
    ci-dessus, une DERNIERE tentative de resolution par correspondance sur
    la priorite finale du ticket (`HlpSlaPolicy.priority == resolved_
    priority`) est effectuee — au plus une politique par priorite est
    attendue en usage normal (aucune contrainte d'unicite DB ne l'impose
    cependant, cf. docstring `HlpSlaPolicy` : rien n'empeche un tenant de
    creer plusieurs politiques pour la meme priorite, auquel cas la
    premiere trouvee est utilisee — un affinage possible si un besoin reel
    de plusieurs politiques concurrentes par priorite se precise). Quand
    une politique est resolue, `first_response_due_at`/`resolution_due_at`
    sont calcules a la creation (`created_at` n'existe pas encore avant
    `.save()`, donc `timezone.now()` sert de reference — meme instant a la
    milliseconde pres)."""
    resolved_priority = priority
    resolved_team = team
    resolved_sla_policy = sla_policy
    if ticket_type is not None:
        if not resolved_priority and ticket_type.default_priority:
            resolved_priority = ticket_type.default_priority
        if resolved_team is None and ticket_type.default_team_id:
            resolved_team = ticket_type.default_team
        if resolved_sla_policy is None and ticket_type.default_sla_policy_id:
            resolved_sla_policy = ticket_type.default_sla_policy
    if not resolved_priority:
        resolved_priority = PRIORITY_NORMAL
    if resolved_sla_policy is None:
        resolved_sla_policy = HlpSlaPolicy.objects.filter(
            tenant=tenant, priority=resolved_priority
        ).first()

    reference = next_reference(tenant, HlpTicket.SEQUENCE_CODE, timezone.now().year)
    now = timezone.now()

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
        sla_policy=resolved_sla_policy,
        blocks_operations=blocks_operations,
        created_by=created_by,
    )
    if resolved_sla_policy is not None:
        ticket.first_response_due_at = now + timedelta(
            minutes=resolved_sla_policy.first_response_minutes
        )
        ticket.resolution_due_at = now + timedelta(minutes=resolved_sla_policy.resolution_minutes)
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


def escalate_ticket(ticket: HlpTicket, user: User | None, *, reason: str = "") -> HlpTicket:
    """Escalade un ticket et persiste la trace correspondante
    (`HlpEscalationEvent`).

    **HD1 -> HD2** : `reason` etait deja present dans la signature en HD1
    mais non persiste (`HlpEscalationEvent` n'existait pas encore) — HD2
    l'exploite desormais pleinement.

    `user` accepte deliberement `None` : c'est le chemin emprunte par
    l'escalade AUTOMATIQUE (`escalation.run_escalation_checks`, cf. sa
    docstring pour la justification complete) — aucune des transitions
    `@transition` de `HlpTicket` ne declare de `permission=` (cf.
    `models.py`), donc `attempt_transition()`/`has_transition_perm()`
    n'exigent pas d'utilisateur reel pour que la transition reussisse
    (verifie directement dans `django_fsm.Transition.has_perm` : sans
    `permission` declare, retourne `True` sans jamais toucher `user`).
    Un appel MANUEL (API/ecran) continue de passer l'utilisateur reel
    (`escalated_by` renseigne sur l'evenement cree) ; l'appel AUTOMATIQUE
    passe `None` (`escalated_by=None` sur l'evenement, `rule` renseigne)."""
    attempt_transition(ticket, "escalate", user)
    ticket.save(update_fields=["state"])
    HlpEscalationEvent.objects.create(
        tenant=ticket.tenant,
        ticket=ticket,
        rule=None,
        escalated_by=user,
        reason=reason,
    )
    publish_event(
        "helpdesk.ticket_escalated",
        {
            "ticket_id": str(ticket.id),
            "reference": ticket.reference,
            "rule_id": None,
            "escalated_by_id": str(user.id) if user is not None else None,
        },
        tenant_id=str(ticket.tenant_id),
    )
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
