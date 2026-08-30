"""HD5 : `services.ai_context_registration` — enregistrement dans le
registre partage et `context_builder` (compteurs reels)."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.ai_context_registry import get_context
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.services.ai_context_registration import _build_context
from apps.helpdesk.services.tickets import create_ticket, escalate_ticket

pytestmark = pytest.mark.django_db


def test_helpdesk_context_is_registered() -> None:
    registered = get_context("helpdesk")
    assert registered is not None
    assert registered.module == "helpdesk"
    assert registered.static_guidance_fr
    assert registered.static_guidance_en
    assert registered.context_builder is _build_context


def test_build_context_counts_open_and_escalated_tickets() -> None:
    tenant = Tenant.objects.create(code="HLP-CTX", name="Helpdesk Context Tenant")
    with use_tenant(tenant.id):
        requester = UserFactory()
        open_ticket = create_ticket(tenant, subject="Ticket ouvert", requester=requester)
        escalated_ticket = create_ticket(tenant, subject="Ticket escalade", requester=requester)
        escalate_ticket(escalated_ticket, requester)

        context = _build_context(str(tenant.id))

    assert context["open_ticket_count"] == 2  # ACTIVE_STATES inclut "escalated"
    assert context["escalated_ticket_count"] == 1
    assert open_ticket.state != escalated_ticket.state
