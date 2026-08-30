"""HD3 : `services.ai_assist.suggest_reply` — discipline fallback-first
mandatee pour toute fonction IA de ce depot (cf. `apps.ai.services.
usage_budget`) : jamais d'appel reseau sans un connecteur reel VRAIMENT
configure, jamais d'exception vers l'appelant."""

from __future__ import annotations

import socket

import pytest
from django.test import override_settings

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import KIND_INCIDENT
from apps.helpdesk.services.ai_assist import suggest_reply
from apps.helpdesk.services.tickets import add_comment, create_ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_requester():
    tenant = Tenant.objects.create(code="HLP-AI", name="Helpdesk AI Tenant")
    with use_tenant(tenant.id):
        requester = UserFactory()
        yield tenant, requester


def test_suggest_reply_never_opens_a_network_socket_without_real_provider(
    tenant_and_requester,
) -> None:
    """Reserve explicitement demandee par le cadrage : `settings.
    AI_PROVIDER_CONFIG` est vide par defaut en test (StubAIProvider) —
    `socket.socket` est patche pour faire echouer le test si quoi que ce
    soit tentait d'en ouvrir un, meme patron exact que `apps.ai.tests.
    test_usage_budget`."""

    def _forbidden_socket(*args, **kwargs):
        raise AssertionError(
            "Un socket reseau a ete ouvert alors qu'aucun fournisseur IA reel "
            "n'est configure — violation de la garantie fallback-first."
        )

    tenant, requester = tenant_and_requester
    with use_tenant(tenant.id):
        ticket = create_ticket(
            tenant, subject="Panne imprimante", requester=requester, kind=KIND_INCIDENT
        )

        original_socket = socket.socket
        socket.socket = _forbidden_socket  # type: ignore[assignment]
        try:
            with override_settings(AI_PROVIDER_CONFIG={}):
                suggestion = suggest_reply(ticket, tenant=tenant)
        finally:
            socket.socket = original_socket  # type: ignore[assignment]

        assert suggestion == ""


def test_suggest_reply_never_raises_with_stub_provider(tenant_and_requester) -> None:
    tenant, requester = tenant_and_requester
    with use_tenant(tenant.id):
        ticket = create_ticket(
            tenant,
            subject="Ecran noir au demarrage",
            requester=requester,
            kind=KIND_INCIDENT,
            description="L'ecran reste noir depuis ce matin.",
        )
        add_comment(ticket, author=requester, body="Toujours pareil apres redemarrage.")

        with override_settings(AI_PROVIDER_CONFIG={}):
            suggestion = suggest_reply(ticket, tenant=tenant)

        assert suggestion == ""
