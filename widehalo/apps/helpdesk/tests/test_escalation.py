"""HD2 : tests de `services.escalation` — `compute_risk_score` (fonction
PURE, unit-testable sans base de donnees sur les instances construites en
memoire, hormis le comptage `escalation_events` qui exige un ticket
persiste) et `run_escalation_checks` (jamais deux fois la meme regle sur
le meme ticket, mais une regle DIFFERENTE peut escalader a nouveau)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import (
    KIND_INCIDENT,
    PRIORITY_LOW,
    PRIORITY_URGENT,
    HlpEscalationEvent,
    HlpEscalationRule,
    HlpTicket,
)
from apps.helpdesk.services.escalation import compute_risk_score, run_escalation_checks
from apps.helpdesk.services.tickets import create_ticket
from apps.helpdesk.tests.factories import (
    HlpEscalationRuleFactory,
    HlpSlaBreachFactory,
    HlpSlaPolicyFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_agent():
    tenant = Tenant.objects.create(code="HLP-ESC", name="Helpdesk Escalation Tenant")
    with use_tenant(tenant.id):
        agent = UserFactory()
        yield tenant, agent


def test_compute_risk_score_urgent_overdue_scores_higher_than_low_with_time_left(
    tenant_and_agent,
) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        urgent_ticket = create_ticket(
            tenant, subject="Urgent", requester=agent, kind=KIND_INCIDENT, priority=PRIORITY_URGENT
        )
        urgent_ticket.resolution_due_at = timezone.now() - timedelta(hours=2)
        urgent_ticket.save(update_fields=["resolution_due_at"])

        low_ticket = create_ticket(
            tenant, subject="Bas", requester=agent, kind=KIND_INCIDENT, priority=PRIORITY_LOW
        )
        low_ticket.resolution_due_at = timezone.now() + timedelta(days=5)
        low_ticket.save(update_fields=["resolution_due_at"])

        assert compute_risk_score(urgent_ticket) > compute_risk_score(low_ticket)


def test_compute_risk_score_is_bounded_and_zero_without_due_dates(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(
            tenant, subject="Sans SLA", requester=agent, kind=KIND_INCIDENT, priority=PRIORITY_LOW
        )
        score = compute_risk_score(ticket)
        assert 0 <= score <= 100
        assert score == 0  # low priority, aucune echeance, aucune escalade anterieure


def test_compute_risk_score_increases_with_prior_escalations(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        before = compute_risk_score(ticket)

        HlpEscalationEvent.objects.create(tenant=tenant, ticket=ticket, reason="manuel")
        ticket.refresh_from_db()

        after = compute_risk_score(ticket)
        assert after > before


def test_run_escalation_checks_creates_event_and_transitions_ticket(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        ticket.created_at = timezone.now() - timedelta(minutes=200)
        ticket.save(update_fields=["created_at"])
        rule = HlpEscalationRuleFactory(
            tenant=tenant,
            condition_type=HlpEscalationRule.CONDITION_TIME_SINCE_CREATED,
            threshold_minutes=120,
        )

        events = run_escalation_checks(tenant)

        assert len(events) == 1
        assert events[0].rule_id == rule.id
        assert events[0].escalated_by_id is None

        reloaded = HlpTicket.objects.get(id=ticket.id)
        assert reloaded.state == HlpTicket.STATE_ESCALATED


def test_run_escalation_checks_never_reapplies_same_rule_twice(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        ticket.created_at = timezone.now() - timedelta(minutes=200)
        ticket.save(update_fields=["created_at"])
        HlpEscalationRuleFactory(
            tenant=tenant,
            condition_type=HlpEscalationRule.CONDITION_TIME_SINCE_CREATED,
            threshold_minutes=120,
        )

        first_run = run_escalation_checks(tenant)
        second_run = run_escalation_checks(tenant)

        assert len(first_run) == 1
        assert len(second_run) == 0
        assert HlpEscalationEvent.objects.filter(ticket=ticket).count() == 1


def test_run_escalation_checks_allows_a_different_rule_to_escalate_again(
    tenant_and_agent,
) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(
            tenant,
            subject="Test",
            requester=agent,
            kind=KIND_INCIDENT,
            priority=PRIORITY_URGENT,
        )
        ticket.created_at = timezone.now() - timedelta(minutes=200)
        ticket.save(update_fields=["created_at"])
        HlpEscalationRuleFactory(
            tenant=tenant,
            condition_type=HlpEscalationRule.CONDITION_TIME_SINCE_CREATED,
            threshold_minutes=120,
        )
        HlpEscalationRuleFactory(
            tenant=tenant,
            condition_type=HlpEscalationRule.CONDITION_MIN_PRIORITY,
            min_priority=PRIORITY_URGENT,
            threshold_minutes=None,
        )

        events = run_escalation_checks(tenant)

        assert len(events) == 2
        assert HlpEscalationEvent.objects.filter(ticket=ticket).count() == 2


def test_run_escalation_checks_sla_breach_condition(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=10, resolution_minutes=20
        )
        ticket = create_ticket(
            tenant, subject="Test", requester=agent, kind=KIND_INCIDENT, sla_policy=policy
        )
        HlpSlaBreachFactory(tenant=tenant, ticket=ticket)
        HlpEscalationRuleFactory(
            tenant=tenant,
            condition_type=HlpEscalationRule.CONDITION_SLA_BREACH,
            threshold_minutes=None,
        )

        events = run_escalation_checks(tenant)

        assert len(events) == 1


def test_run_escalation_checks_ignores_inactive_rules(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        ticket.created_at = timezone.now() - timedelta(minutes=200)
        ticket.save(update_fields=["created_at"])
        rule = HlpEscalationRuleFactory(
            tenant=tenant,
            condition_type=HlpEscalationRule.CONDITION_TIME_SINCE_CREATED,
            threshold_minutes=120,
        )
        rule.is_active = False
        rule.save(update_fields=["is_active"])

        events = run_escalation_checks(tenant)

        assert events == []
