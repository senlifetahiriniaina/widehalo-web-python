"""HD1 : tests de niveau service/modele pour `HlpTicket` (FSM) et
`HlpTicketTypeCatalog` (pre-remplissage priorite/equipe depuis le type)."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.helpdesk.models import KIND_INCIDENT, PRIORITY_HIGH, HlpTicket
from apps.helpdesk.services.tickets import (
    assign_ticket,
    close_ticket,
    create_ticket,
    escalate_ticket,
    resolve_ticket,
)
from apps.helpdesk.tests.factories import HlpTeamFactory, HlpTicketTypeCatalogFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_agent():
    tenant = Tenant.objects.create(code="HLP-MODEL", name="Helpdesk Model Tenant")
    with use_tenant(tenant.id):
        agent = UserFactory()
        grant_role(agent, "admin")
        yield tenant, agent


def test_create_ticket_prefills_priority_and_team_from_type(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        team = HlpTeamFactory(tenant=tenant)
        ticket_type = HlpTicketTypeCatalogFactory(
            tenant=tenant,
            kind=KIND_INCIDENT,
            default_priority=PRIORITY_HIGH,
            default_team=team,
        )
        ticket = create_ticket(
            tenant,
            subject="Panne machine",
            requester=agent,
            kind=KIND_INCIDENT,
            ticket_type=ticket_type,
        )
        assert ticket.priority == PRIORITY_HIGH
        assert ticket.team_id == team.id
        assert ticket.reference.startswith("HLP-")


def test_ticket_fsm_happy_path(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        assert ticket.state == HlpTicket.STATE_NEW

        assign_ticket(ticket, agent)
        assert ticket.state == HlpTicket.STATE_IN_PROGRESS

        resolve_ticket(ticket, agent)
        assert ticket.state == HlpTicket.STATE_RESOLVED
        assert ticket.resolved_at is not None

        close_ticket(ticket, agent)
        assert ticket.state == HlpTicket.STATE_CLOSED
        assert ticket.closed_at is not None


def test_ticket_escalation_manual(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        escalate_ticket(ticket, agent)
        assert ticket.state == HlpTicket.STATE_ESCALATED
        # `risk_score` reste a 0 en HD1 (calcul deterministe differe a HD2).
        assert ticket.risk_score == 0


def test_ticket_reference_refetch_persists(tenant_and_agent) -> None:
    """Verifie que la transition persiste bien en base (pas seulement sur
    l'instance Python en memoire) — recharge explicite via un NOUVEL objet."""
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = create_ticket(tenant, subject="Test", requester=agent, kind=KIND_INCIDENT)
        assign_ticket(ticket, agent)

        reloaded = HlpTicket.objects.get(id=ticket.id)
        assert reloaded.state == HlpTicket.STATE_IN_PROGRESS
