"""Service SLA `helpdesk` (HD2, cf. plan section « SLA et escalade — 100%
deterministe ») : `check_breaches(tenant)` compare `now()` aux echeances
`first_response_due_at`/`resolution_due_at` de chaque ticket actif avec une
`sla_policy` resolue, cree un `HlpSlaBreach` de facon IDEMPOTENTE (jamais un
doublon, garanti au niveau applicatif ET par `UniqueConstraint(ticket,
breach_type)` en base), et recalcule `HlpTicket.risk_score` (fonction
deterministe `escalation.compute_risk_score`, cf. sa docstring) pour CHAQUE
ticket actif dans la meme passe — que celui-ci ait ou non une `sla_policy`
resolue (le risque d'escalade depend aussi de la priorite/du nombre
d'escalades anterieures, facteurs pertinents meme sans SLA)."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.helpdesk.models import HlpSlaBreach, HlpTicket
from apps.helpdesk.services.escalation import compute_risk_score


def _minutes_over(now: datetime, due_at: datetime) -> int:
    return max(0, int((now - due_at).total_seconds() // 60))


def check_breaches(tenant: Tenant) -> list[HlpSlaBreach]:
    now = timezone.now()
    created: list[HlpSlaBreach] = []

    tickets = HlpTicket.objects.filter(tenant=tenant, state__in=HlpTicket.ACTIVE_STATES)
    for ticket in tickets:
        if ticket.sla_policy_id is not None:
            if (
                ticket.first_responded_at is None
                and ticket.first_response_due_at is not None
                and now > ticket.first_response_due_at
                and not HlpSlaBreach.objects.filter(
                    ticket=ticket, breach_type=HlpSlaBreach.BREACH_FIRST_RESPONSE
                ).exists()
            ):
                created.append(
                    HlpSlaBreach.objects.create(
                        tenant=tenant,
                        ticket=ticket,
                        breach_type=HlpSlaBreach.BREACH_FIRST_RESPONSE,
                        breached_at=now,
                        minutes_over=_minutes_over(now, ticket.first_response_due_at),
                    )
                )
            if (
                ticket.resolved_at is None
                and ticket.resolution_due_at is not None
                and now > ticket.resolution_due_at
                and not HlpSlaBreach.objects.filter(
                    ticket=ticket, breach_type=HlpSlaBreach.BREACH_RESOLUTION
                ).exists()
            ):
                created.append(
                    HlpSlaBreach.objects.create(
                        tenant=tenant,
                        ticket=ticket,
                        breach_type=HlpSlaBreach.BREACH_RESOLUTION,
                        breached_at=now,
                        minutes_over=_minutes_over(now, ticket.resolution_due_at),
                    )
                )

        new_score = compute_risk_score(ticket)
        if new_score != ticket.risk_score:
            ticket.risk_score = new_score
            ticket.save(update_fields=["risk_score"])

    return created
