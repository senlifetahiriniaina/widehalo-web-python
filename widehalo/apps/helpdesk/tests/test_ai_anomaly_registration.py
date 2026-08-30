"""HD5 : `services.ai_anomaly_registration` — verifie que le check
surface uniquement les tickets genuinement a risque (score eleve OU
echeance SLA imminente/depassee), jamais un ticket calme, et que la
severite reflete correctement le cas overdue."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    get_anomaly_check,
)
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.services.ai_anomaly_registration import _check_tickets_at_risk
from apps.helpdesk.services.tickets import create_ticket
from apps.helpdesk.tests.factories import HlpSlaPolicyFactory

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("helpdesk.ticket_at_risk")
    assert registered is not None
    assert registered.module == "helpdesk"
    assert registered.function is _check_tickets_at_risk


def test_check_ignores_a_calm_ticket() -> None:
    tenant = Tenant.objects.create(code="HLP-AI3-1", name="Helpdesk AI3 Tenant 1")
    with use_tenant(tenant.id):
        requester = UserFactory()
        sla_policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=4 * 60, resolution_minutes=48 * 60
        )
        create_ticket(
            tenant,
            subject="Ticket calme",
            requester=requester,
            sla_policy=sla_policy,
        )

        candidates = _check_tickets_at_risk(str(tenant.id))

    # risk_score reste a 0 (aucun recalcul n'a encore ete effectue par
    # `run_escalation_checks`), et les deux echeances (premiere reponse 4h,
    # resolution 48h) sont loin au-dela de la fenetre "due soon" de 2h ->
    # aucune anomalie.
    assert candidates == []


def test_check_flags_high_risk_score_ticket_as_high_severity() -> None:
    tenant = Tenant.objects.create(code="HLP-AI3-2", name="Helpdesk AI3 Tenant 2")
    with use_tenant(tenant.id):
        requester = UserFactory()
        ticket = create_ticket(tenant, subject="Ticket a fort risque", requester=requester)
        ticket.risk_score = 95
        ticket.save(update_fields=["risk_score"])

        candidates = _check_tickets_at_risk(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "helpdesk.hlpticket"
    assert candidate.object_id == str(ticket.id)
    assert candidate.severity == SEVERITY_HIGH
    assert str(ticket.risk_score) in candidate.description


def test_check_flags_moderately_at_risk_ticket_as_medium_severity() -> None:
    tenant = Tenant.objects.create(code="HLP-AI3-3", name="Helpdesk AI3 Tenant 3")
    with use_tenant(tenant.id):
        requester = UserFactory()
        ticket = create_ticket(tenant, subject="Ticket a risque modere", requester=requester)
        ticket.risk_score = 75
        ticket.save(update_fields=["risk_score"])

        candidates = _check_tickets_at_risk(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_MEDIUM


def test_check_flags_overdue_ticket_as_high_severity() -> None:
    tenant = Tenant.objects.create(code="HLP-AI3-4", name="Helpdesk AI3 Tenant 4")
    with use_tenant(tenant.id):
        requester = UserFactory()
        sla_policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=60, resolution_minutes=60
        )
        ticket = create_ticket(
            tenant, subject="Ticket en retard", requester=requester, sla_policy=sla_policy
        )
        # Deja depasse l'echeance de resolution, jamais resolu.
        ticket.resolution_due_at = timezone.now() - timedelta(minutes=5)
        ticket.save(update_fields=["resolution_due_at"])

        candidates = _check_tickets_at_risk(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_HIGH


def test_check_ignores_resolved_ticket_even_with_high_score() -> None:
    tenant = Tenant.objects.create(code="HLP-AI3-5", name="Helpdesk AI3 Tenant 5")
    with use_tenant(tenant.id):
        from apps.helpdesk.services.tickets import assign_ticket, resolve_ticket

        requester = UserFactory()
        ticket = create_ticket(tenant, subject="Ticket resolu", requester=requester)
        ticket.risk_score = 100
        ticket.save(update_fields=["risk_score"])
        assign_ticket(ticket, requester)
        resolve_ticket(ticket, requester)

        candidates = _check_tickets_at_risk(str(tenant.id))

    assert candidates == []
