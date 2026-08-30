"""Service d'escalade `helpdesk` (HD2, cf. plan section « SLA et escalade
— 100% deterministe »).

- `compute_risk_score(ticket)` : heuristique DETERMINISTE (jamais un
  modele entraine/ML/LLM, decision de perimetre n°2 actee avec
  l'utilisateur, cf. plan) qui remplace la « prediction d'escalade » du
  document source. Formule disclosed dans sa propre docstring.
- `run_escalation_checks(tenant)` : evalue chaque `HlpEscalationRule`
  active contre chaque ticket actif, cree un `HlpEscalationEvent` par
  couple (ticket, regle) nouvellement matche (jamais deux fois la meme
  regle sur le meme ticket), transite le ticket vers `escalated` quand
  c'est encore possible, applique `escalate_to_team`/`escalate_to_user`,
  notifie, et publie `"helpdesk.ticket_escalated"`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from django.utils import timezone
from django_fsm import TransitionNotAllowed

from apps.core.events import publish_event
from apps.core.models.tenant import Tenant
from apps.core.services.notifications import dispatch_notification, notify_role
from apps.core.services.workflow import TransitionPermissionError, attempt_transition
from apps.helpdesk.models import (
    PRIORITY_ORDER,
    HlpEscalationEvent,
    HlpEscalationRule,
    HlpTicket,
)

# Poids de priorite pour `compute_risk_score` (cf. sa docstring) — memes 4
# valeurs exactes que `HlpTicket.priority`, un simple dict plutot qu'un
# mecanisme generique, suffisant pour 4 valeurs fixes (meme discipline que
# `PRIORITY_ORDER` dans `models.py`).
_PRIORITY_WEIGHT: Final[dict[str, int]] = {
    "low": 0,
    "normal": 5,
    "high": 15,
    "urgent": 25,
}
_MAX_ESCALATION_COMPONENT: Final[int] = 25
_ESCALATION_COMPONENT_PER_EVENT: Final[int] = 10
_MAX_TIME_COMPONENT: Final[float] = 50.0
_TIME_RATIO_CAP: Final[float] = 2.0


def compute_risk_score(ticket: HlpTicket) -> int:
    """Score de risque d'escalade DETERMINISTE, 0-100, remplace la
    « prediction ML d'escalade » du document source (decision de perimetre
    n°2, cf. plan) — **jamais un modele entraine, jamais une bibliotheque
    de statistiques/ML**, une somme ponderee de 3 facteurs REELS,
    reproductible et explicable :

    1. **Composante temporelle (0-50 points)** : ratio temps ecoule / temps
       alloue jusqu'a l'echeance SLA la plus proche PAS ENCORE atteinte
       (`first_response_due_at` si `first_responded_at is None`,
       `resolution_due_at` si `resolved_at is None` — la plus proche des
       deux si les deux sont pertinentes). `ratio = (now - created_at) /
       (due_at - created_at)`, plafonne a 2.0 (un ticket 2x plus vieux que
       son delai alloue n'est pas "plus a risque" qu'un ticket 2.5x plus
       vieux au sens de ce score — la composante sature). Composante =
       `min(ratio, 2.0) / 2.0 * 50` : 0 point a la creation, 25 points pile
       a l'echeance (ratio=1), 50 points au double du delai alloue ou plus.
       Aucune politique SLA resolue, ou aucune echeance encore pertinente
       (premiere reponse ET resolution deja actees) -> 0 point.
    2. **Composante priorite (0-25 points)** : `low`=0, `normal`=5,
       `high`=15, `urgent`=25 — un ticket urgent est intrinsequement plus
       a risque qu'un ticket bas, meme a ratio temporel egal.
    3. **Composante recurrence d'escalade (0-25 points)** : `10 x nombre
       d'HlpEscalationEvent deja enregistres pour ce ticket`, plafonne a
       25 (un ticket deja escalade au moins une fois est intrinsequement
       plus a risque de l'etre a nouveau — facteur REEL, pas une
       supposition) — 3 escalades anterieures ou plus saturent la
       composante.

    Somme plafonnee a 100 (borne naturelle : 50+25+25=100, `min()`
    explicite malgre tout par prudence si la ponderation venait a
    changer). Fonction PURE au sens metier (une seule requete DB pour
    compter les evenements d'escalade du ticket, aucun appel reseau/LLM),
    directement unit-testable avec une instance `HlpTicket` construite en
    memoire."""
    time_component = 0.0
    now = timezone.now()
    candidates: list[datetime] = []
    if ticket.first_responded_at is None and ticket.first_response_due_at is not None:
        candidates.append(ticket.first_response_due_at)
    if ticket.resolved_at is None and ticket.resolution_due_at is not None:
        candidates.append(ticket.resolution_due_at)
    if candidates:
        nearest_due = min(candidates)
        total_seconds = (nearest_due - ticket.created_at).total_seconds()
        elapsed_seconds = (now - ticket.created_at).total_seconds()
        ratio = elapsed_seconds / total_seconds if total_seconds > 0 else _TIME_RATIO_CAP
        ratio = max(0.0, min(ratio, _TIME_RATIO_CAP))
        time_component = ratio / _TIME_RATIO_CAP * _MAX_TIME_COMPONENT

    priority_component = _PRIORITY_WEIGHT.get(ticket.priority, 0)
    escalation_count = ticket.escalation_events.count()
    escalation_component = min(
        escalation_count * _ESCALATION_COMPONENT_PER_EVENT, _MAX_ESCALATION_COMPONENT
    )

    score = round(time_component + priority_component + escalation_component)
    return max(0, min(100, score))


def _rule_matches(rule: HlpEscalationRule, ticket: HlpTicket, now: datetime) -> bool:
    """`min_priority`, quand renseigne sur une regle dont le
    `condition_type` n'est PAS `min_priority`, s'applique comme filtre
    ADDITIONNEL (cf. docstring `HlpEscalationRule`) — verifie en dernier,
    apres la condition principale, jamais a la place."""
    matched: bool
    if rule.condition_type == HlpEscalationRule.CONDITION_TIME_SINCE_CREATED:
        matched = rule.threshold_minutes is not None and (
            now - ticket.created_at >= timedelta(minutes=rule.threshold_minutes)
        )
    elif rule.condition_type == HlpEscalationRule.CONDITION_TIME_SINCE_LAST_ACTIVITY:
        last_comment = ticket.comments.order_by("-created_at").first()
        last_activity = last_comment.created_at if last_comment is not None else ticket.created_at
        matched = rule.threshold_minutes is not None and (
            now - last_activity >= timedelta(minutes=rule.threshold_minutes)
        )
    elif rule.condition_type == HlpEscalationRule.CONDITION_SLA_BREACH:
        matched = ticket.sla_breaches.exists()
    elif rule.condition_type == HlpEscalationRule.CONDITION_MIN_PRIORITY:
        matched = bool(rule.min_priority) and PRIORITY_ORDER.get(
            ticket.priority, 0
        ) >= PRIORITY_ORDER.get(rule.min_priority, 0)
    else:  # pragma: no cover — choix de modele exhaustifs ci-dessus.
        matched = False

    if (
        matched
        and rule.condition_type != HlpEscalationRule.CONDITION_MIN_PRIORITY
        and rule.min_priority
    ):
        matched = PRIORITY_ORDER.get(ticket.priority, 0) >= PRIORITY_ORDER.get(rule.min_priority, 0)
    return matched


def _reason_for_rule(rule: HlpEscalationRule, ticket: HlpTicket) -> str:
    if rule.condition_type == HlpEscalationRule.CONDITION_TIME_SINCE_CREATED:
        detail = f"ouvert depuis plus de {rule.threshold_minutes} minute(s)"
    elif rule.condition_type == HlpEscalationRule.CONDITION_TIME_SINCE_LAST_ACTIVITY:
        detail = f"sans activite depuis plus de {rule.threshold_minutes} minute(s)"
    elif rule.condition_type == HlpEscalationRule.CONDITION_SLA_BREACH:
        detail = "au moins une breche de SLA enregistree"
    else:
        detail = f"priorite >= {rule.min_priority}"
    return f"Escalade automatique — regle « {rule.name} » : {detail} (ticket {ticket.reference})."


def _notify_escalation(
    tenant: Tenant, rule: HlpEscalationRule, ticket: HlpTicket, reason: str
) -> None:
    """Notifie les destinataires pertinents d'une escalade automatique.

    **Choix de conception disclosed** : `notify_role` (cf. `apps.core.
    services.notifications`) est cle sur un `Group` Django global (un
    role), pas sur un `HlpTeam` arbitraire — inadapte pour « notifier tous
    les membres d'une equipe Helpdesk precise ». Quand `rule.
    escalate_to_team` est renseigne, on itere donc `team.members.all()` et
    on appelle `dispatch_notification` PAR membre (l'autre primitive
    exposee par `apps.core.services.notifications`, deja recommandee pour
    ce cas par le plan). Sans equipe cible explicite, on retombe sur
    `notify_role(..., "direction", ...)` — aucun role "agent support"
    n'existe dans les 11 roles (meme constat que RBAC ci-dessus), et
    `direction` est le role de pilotage transverse deja utilise partout
    ailleurs dans ce depot pour ce genre d'alerte generique (cf.
    `presence.run_presence_maintenance` -> role `rh` pour un besoin
    analogue mais domaine-specifique ; ici aucun domaine ne se degage,
    d'ou `direction`). Si `rule.escalate_to_user` est EN PLUS renseigne, ce
    destinataire individuel est TOUJOURS notifie directement, qu'une
    equipe cible ait ete notifiee ou non (un destinataire nomme explicite
    ne doit jamais dependre de son appartenance a l'equipe notifiee)."""
    payload = {
        "ticket_id": str(ticket.id),
        "reference": ticket.reference,
        "rule_id": str(rule.id),
        "reason": reason,
    }
    team = rule.escalate_to_team
    if team is not None:
        for member in team.members.all():
            dispatch_notification(
                member, "helpdesk.ticket_escalated", payload, tenant_id=str(tenant.id)
            )
    else:
        notify_role(str(tenant.id), "direction", "helpdesk.ticket_escalated", payload)

    target_user = rule.escalate_to_user
    if target_user is not None:
        dispatch_notification(
            target_user, "helpdesk.ticket_escalated", payload, tenant_id=str(tenant.id)
        )


def _apply_rule_match(
    tenant: Tenant, ticket: HlpTicket, rule: HlpEscalationRule
) -> HlpEscalationEvent:
    """Applique une regle AUTOMATIQUE deja verifiee correspondre a `ticket`
    (cf. `run_escalation_checks`) : cree l'`HlpEscalationEvent`, transite le
    ticket si encore possible, applique `escalate_to_team`/
    `escalate_to_user`, publie l'evenement et notifie.

    `ticket: HlpTicket` annote explicitement (plutot qu'inline dans la
    boucle de `run_escalation_checks`) pour que le garde-fou AST `tests/
    architecture/test_attempt_transition_saves_state.py` puisse resoudre le
    champ FSM depuis l'annotation du parametre — meme discipline que
    partout ailleurs dans ce depot, cf. sa propre docstring."""
    reason = _reason_for_rule(rule, ticket)
    event = HlpEscalationEvent.objects.create(
        tenant=tenant, ticket=ticket, rule=rule, escalated_by=None, reason=reason
    )

    try:
        attempt_transition(ticket, "escalate", None)
        ticket.save(update_fields=["state"])
    except (TransitionNotAllowed, TransitionPermissionError):
        # Ticket deja `escalated` (escalade anterieure, manuelle ou par une
        # autre regle) : `escalated` n'est pas un etat source valide pour
        # `escalate`, donc `has_transition_perm` renvoie `False` AVANT meme
        # de consulter la permission (`FSMMeta.has_transition_perm` retourne
        # `False` des que `get_transition(state)` echoue) — ce qui fait
        # lever `TransitionPermissionError`, PAS `TransitionNotAllowed`
        # (reserve au cas, plus rare ici, ou la garde passe mais la
        # transition elle-meme refuse). Les deux sont donc interceptees
        # identiquement : l'evenement/la notification restent crees meme
        # si l'etat FSM ne change plus.
        pass

    update_fields: list[str] = []
    if rule.escalate_to_team_id:
        ticket.team = rule.escalate_to_team
        update_fields.append("team")
    if rule.escalate_to_user_id:
        ticket.assignee = rule.escalate_to_user
        update_fields.append("assignee")
    if update_fields:
        ticket.save(update_fields=update_fields)

    publish_event(
        "helpdesk.ticket_escalated",
        {
            "ticket_id": str(ticket.id),
            "reference": ticket.reference,
            "rule_id": str(rule.id),
            "escalated_by_id": None,
        },
        tenant_id=str(tenant.id),
    )
    _notify_escalation(tenant, rule, ticket, reason)
    return event


def run_escalation_checks(tenant: Tenant) -> list[HlpEscalationEvent]:
    """Evalue chaque `HlpEscalationRule` active contre chaque ticket actif
    (`HlpTicket.ACTIVE_STATES`) — jamais deux fois la MEME regle sur le
    MEME ticket (verifie par l'existence prealable d'un `HlpEscalationEvent
    (ticket=ticket, rule=rule)`), mais un ticket PEUT etre escalade a
    nouveau par une regle DIFFERENTE, ou manuellement plus tard (cf. plan).

    **Choix disclosed — transition FSM automatique** : la transition
    `escalate` de `HlpTicket` ne declare aucun `permission=` (cf.
    `models.py`), donc `attempt_transition(ticket, "escalate", None)`
    reussit sans utilisateur reel (verifie directement dans
    `django_fsm.Transition.has_perm` : sans `permission`, retourne `True`
    sans jamais toucher `user`) — inutile de fabriquer un « utilisateur
    systeme » factice. Si le ticket est DEJA dans l'etat `escalated`
    (escalade anterieure, manuelle ou par une autre regle), la transition
    echoue normalement (`escalated` n'est pas un etat source valide pour
    `escalate`) : ce cas est intercepte explicitement (`TransitionNotAllowed`
    ET `TransitionPermissionError` — `FSMMeta.has_transition_perm` refuse
    AVANT meme de consulter la permission des qu'aucune transition n'existe
    depuis l'etat courant, ce qui fait lever la seconde plutot que la
    premiere, cf. `_apply_rule_match`) et n'empeche PAS la creation de
    l'evenement/la notification — un ticket deja escalade continue
    d'accumuler son historique d'escalade meme si son etat FSM ne change
    plus.

    **Choix disclosed — creation de l'evenement, pas via `services.tickets.
    escalate_ticket()`** : cette derniere cree TOUJOURS un evenement
    `rule=None` (contrat du chemin MANUEL, cf. sa docstring) ; l'appeler
    ici produirait un evenement automatique attribue a AUCUNE regle,
    perdant l'information demandee par le plan. Cette fonction reproduit
    donc directement les 2 lignes `attempt_transition()`+
    `.save(update_fields=["state"])` (meme garde-fou AST) et cree son
    propre `HlpEscalationEvent(rule=rule, escalated_by=None)`."""
    now = timezone.now()
    created_events: list[HlpEscalationEvent] = []
    rules = list(HlpEscalationRule.objects.filter(tenant=tenant, is_active=True))
    if not rules:
        return created_events

    tickets = HlpTicket.objects.filter(tenant=tenant, state__in=HlpTicket.ACTIVE_STATES)
    for ticket in tickets:
        new_score = compute_risk_score(ticket)
        if new_score != ticket.risk_score:
            ticket.risk_score = new_score
            ticket.save(update_fields=["risk_score"])

        for rule in rules:
            if HlpEscalationEvent.objects.filter(ticket=ticket, rule=rule).exists():
                continue
            if not _rule_matches(rule, ticket, now):
                continue
            created_events.append(_apply_rule_match(tenant, ticket, rule))

    return created_events
