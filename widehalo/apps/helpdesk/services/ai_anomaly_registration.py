"""AI3 : auto-enregistrement d'une verification d'anomalie DETERMINISTE du
module `helpdesk` dans `core.services.anomaly_registry`, appele depuis
`apps.py::ready()` — meme patron exact que `apps.stocks.services.
ai_anomaly_registration.register_ai_anomaly_checks()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_check_tickets_at_risk`
ne fait QUE surfacer `HlpTicket.risk_score`/`first_response_due_at`/
`resolution_due_at`, TOUS DEJA calcules de facon deterministe par HD2
(`services.escalation.compute_risk_score`/`services.tickets.create_ticket`)
— aucun nouveau calcul introduit ici, 100% deterministe comme le reste de
ce registre (`sales.forecast_gap`, `stocks.negative_stock`).

**Seuils choisis et disclosed** (aucune reference normative externe, un
point de depart raisonnable) :
- `risk_score >= _RISK_SCORE_THRESHOLD` (70/100, cf. `compute_risk_score`
  qui plafonne a 100 — 70 correspond a un ticket deja bien engage sur au
  moins deux des trois facteurs, ex. priorite haute + ratio temporel proche
  de l'echeance) declenche une anomalie ;
- OU une echeance SLA (premiere reponse ou resolution, cf. `HlpTicket.
  first_response_due_at`/`resolution_due_at`) tombe dans les
  `_DUE_SOON_WINDOW` (2h) a venir et n'est pas encore actee
  (`first_responded_at`/`resolved_at is None`) — signal complementaire au
  score (un ticket recemment cree avec une SLA courte peut avoir un score
  encore bas mais une echeance imminente).

**Severite** : `SEVERITY_HIGH` si le score est deja tres eleve
(`>= _RISK_SCORE_HIGH_THRESHOLD`, 90/100) OU si une echeance est DEJA
depassee (breche non encore constatee par `sla.check_breaches`, run
periodique separe) ; `SEVERITY_MEDIUM` sinon (score moderement eleve ou
echeance proche mais pas encore depassee)."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AnomalyCandidate,
    register_anomaly_check,
)

_RISK_SCORE_THRESHOLD = 70
_RISK_SCORE_HIGH_THRESHOLD = 90
_DUE_SOON_WINDOW = timedelta(hours=2)


def _check_tickets_at_risk(tenant_id: str) -> list[AnomalyCandidate]:
    from apps.helpdesk.models import HlpTicket

    now = timezone.now()
    soon = now + _DUE_SOON_WINDOW

    tickets = HlpTicket.objects.filter(
        tenant_id=tenant_id, state__in=HlpTicket.ACTIVE_STATES
    ).filter(
        Q(risk_score__gte=_RISK_SCORE_THRESHOLD)
        | Q(
            resolution_due_at__isnull=False,
            resolution_due_at__lte=soon,
            resolved_at__isnull=True,
        )
        | Q(
            first_response_due_at__isnull=False,
            first_response_due_at__lte=soon,
            first_responded_at__isnull=True,
        )
    )

    candidates: list[AnomalyCandidate] = []
    for ticket in tickets:
        overdue = (
            ticket.resolution_due_at is not None
            and ticket.resolution_due_at <= now
            and ticket.resolved_at is None
        ) or (
            ticket.first_response_due_at is not None
            and ticket.first_response_due_at <= now
            and ticket.first_responded_at is None
        )
        severity = (
            SEVERITY_HIGH
            if ticket.risk_score >= _RISK_SCORE_HIGH_THRESHOLD or overdue
            else SEVERITY_MEDIUM
        )

        due_bits = []
        if (
            ticket.resolution_due_at is not None
            and ticket.resolved_at is None
            and ticket.resolution_due_at <= soon
        ):
            due_bits.append(f"resolution due le {ticket.resolution_due_at.isoformat()}")
        if (
            ticket.first_response_due_at is not None
            and ticket.first_responded_at is None
            and ticket.first_response_due_at <= soon
        ):
            due_bits.append(f"premiere reponse due le {ticket.first_response_due_at.isoformat()}")
        due_note = f" ; {' ; '.join(due_bits)}" if due_bits else ""

        candidates.append(
            AnomalyCandidate(
                content_type_label="helpdesk.hlpticket",
                object_id=str(ticket.id),
                severity=severity,
                description=(
                    f"Ticket {ticket.reference} a risque d'escalade "
                    f"(score de risque {ticket.risk_score}/100){due_note}."
                ),
            )
        )

    return candidates


def register_ai_anomaly_checks() -> None:
    register_anomaly_check(
        "helpdesk.ticket_at_risk",
        module="helpdesk",
        label="Ticket a risque de breche SLA/escalade imminente",
        function=_check_tickets_at_risk,
    )
