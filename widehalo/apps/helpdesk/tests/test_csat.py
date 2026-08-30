"""HD4 : tests de `services.csat.submit_csat_response` — refus sur ticket
non resolu/cloture, refus de double soumission, acceptation valide."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import KIND_INCIDENT, HlpCsatResponse, HlpTicket
from apps.helpdesk.services.csat import submit_csat_response
from apps.helpdesk.services.tickets import (
    assign_ticket,
    close_ticket,
    create_ticket,
    resolve_ticket,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_agent():
    tenant = Tenant.objects.create(code="HLP-CSAT", name="Helpdesk CSAT Tenant")
    with use_tenant(tenant.id):
        agent = UserFactory()
        yield tenant, agent


def _new_ticket(tenant, agent) -> HlpTicket:
    return create_ticket(tenant, subject="Test CSAT", requester=agent, kind=KIND_INCIDENT)


def test_submit_csat_response_refuses_when_ticket_not_resolved(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = _new_ticket(tenant, agent)  # etat "new"

        with pytest.raises(ValidationError):
            submit_csat_response(ticket, score=5)

        assert HlpCsatResponse.objects.filter(ticket=ticket).count() == 0


def test_submit_csat_response_refuses_out_of_range_score(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = _new_ticket(tenant, agent)
        assign_ticket(ticket, agent)
        resolve_ticket(ticket, agent)

        for bad_score in (0, 6, -1):
            with pytest.raises(ValidationError):
                submit_csat_response(ticket, score=bad_score)


def test_submit_csat_response_accepts_valid_response_on_resolved_ticket(
    tenant_and_agent,
) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = _new_ticket(tenant, agent)
        assign_ticket(ticket, agent)
        resolve_ticket(ticket, agent)

        response = submit_csat_response(ticket, score=4, comment="Bon service.")

        assert response.score == 4
        assert response.comment == "Bon service."
        assert response.ticket_id == ticket.id
        assert response.tenant_id == tenant.id


def test_submit_csat_response_accepts_on_closed_ticket(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = _new_ticket(tenant, agent)
        assign_ticket(ticket, agent)
        resolve_ticket(ticket, agent)
        close_ticket(ticket, agent)

        response = submit_csat_response(ticket, score=3)
        assert response.score == 3


def test_submit_csat_response_refuses_second_submission(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        ticket = _new_ticket(tenant, agent)
        assign_ticket(ticket, agent)
        resolve_ticket(ticket, agent)

        submit_csat_response(ticket, score=5)

        with pytest.raises(ValidationError):
            submit_csat_response(ticket, score=2)

        assert HlpCsatResponse.objects.filter(ticket=ticket).count() == 1
