"""HD5 : `services.ai_advisor_registration` — recommandation UNIQUEMENT
quand un meme type de ticket est escalade au moins 3 fois recemment,
jamais en-dessous du seuil."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.advisor_rule_registry import get_advisor_rule
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.services.ai_advisor_registration import _advise_on_helpdesk
from apps.helpdesk.services.tickets import create_ticket, escalate_ticket
from apps.helpdesk.tests.factories import HlpTicketTypeCatalogFactory

pytestmark = pytest.mark.django_db


def test_rule_is_registered_in_the_shared_registry() -> None:
    registered = get_advisor_rule("helpdesk.escalation_advisor")
    assert registered is not None
    assert registered.module == "helpdesk"
    assert registered.function is _advise_on_helpdesk


def test_no_recommendation_below_recurrence_threshold() -> None:
    tenant = Tenant.objects.create(code="HLP-AI7-1", name="Helpdesk AI7 Tenant 1")
    with use_tenant(tenant.id):
        requester = UserFactory()
        ticket_type = HlpTicketTypeCatalogFactory(tenant=tenant, label="Panne machine")
        for _i in range(2):
            ticket = create_ticket(
                tenant, subject="Incident", requester=requester, ticket_type=ticket_type
            )
            escalate_ticket(ticket, requester)

        candidates = _advise_on_helpdesk(str(tenant.id), "helpdesk.list", "direction")

    assert candidates == []


def test_recommendation_fires_at_recurrence_threshold() -> None:
    tenant = Tenant.objects.create(code="HLP-AI7-2", name="Helpdesk AI7 Tenant 2")
    with use_tenant(tenant.id):
        requester = UserFactory()
        ticket_type = HlpTicketTypeCatalogFactory(tenant=tenant, label="Panne machine")
        for _i in range(3):
            ticket = create_ticket(
                tenant, subject="Incident", requester=requester, ticket_type=ticket_type
            )
            escalate_ticket(ticket, requester)

        candidates = _advise_on_helpdesk(str(tenant.id), "helpdesk.list", "direction")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.target_module == "helpdesk"
    assert candidate.target_action_code == "helpdesk.create_ticket_from_event"
    assert "Panne machine" in candidate.label
