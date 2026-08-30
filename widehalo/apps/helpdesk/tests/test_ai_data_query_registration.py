"""GW3 : adaptateurs `apps.helpdesk.services.ai_data_query_registration` —
`helpdesk.ticket_summary` (agregation de comptes par statut) et
`helpdesk.search_kb` (enveloppe de `services.kb.search_articles`)."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.data_query_tool_registry import get_data_query_tool
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.services.ai_data_query_registration import (
    _tool_search_kb,
    _tool_ticket_summary,
)
from apps.helpdesk.services.kb import publish_article
from apps.helpdesk.services.tickets import create_ticket, escalate_ticket
from apps.helpdesk.tests.factories import HlpKbArticleFactory, HlpTeamFactory

pytestmark = pytest.mark.django_db


def test_ticket_summary_tool_is_registered() -> None:
    tool = get_data_query_tool("helpdesk.ticket_summary")
    assert tool is not None
    assert tool.module == "helpdesk"
    assert tool.required_permission == "helpdesk.view_hlpticket"
    assert tool.function is _tool_ticket_summary


def test_search_kb_tool_is_registered() -> None:
    tool = get_data_query_tool("helpdesk.search_kb")
    assert tool is not None
    assert tool.module == "helpdesk"
    assert tool.required_permission == "helpdesk.view_hlpkbarticle"
    assert tool.function is _tool_search_kb


def test_ticket_summary_counts_by_state() -> None:
    tenant = Tenant.objects.create(code="HLP-GW3-1", name="Helpdesk GW3 Tenant 1")
    with use_tenant(tenant.id):
        requester = UserFactory()
        user = UserFactory()
        team = HlpTeamFactory(tenant=tenant)
        create_ticket(tenant, subject="Ouvert", requester=requester, team=team)
        escalated = create_ticket(tenant, subject="Escalade", requester=requester, team=team)
        escalate_ticket(escalated, requester)

        rows = _tool_ticket_summary(tenant, user)

    assert rows == [{"open_count": 2, "resolved_count": 0, "closed_count": 0, "escalated_count": 1}]


def test_ticket_summary_filters_by_team() -> None:
    tenant = Tenant.objects.create(code="HLP-GW3-2", name="Helpdesk GW3 Tenant 2")
    with use_tenant(tenant.id):
        requester = UserFactory()
        user = UserFactory()
        team_a = HlpTeamFactory(tenant=tenant)
        team_b = HlpTeamFactory(tenant=tenant)
        create_ticket(tenant, subject="Equipe A", requester=requester, team=team_a)
        create_ticket(tenant, subject="Equipe B", requester=requester, team=team_b)

        rows = _tool_ticket_summary(tenant, user, team_id=str(team_a.id))

    assert rows[0]["open_count"] == 1


def test_search_kb_returns_published_matching_articles_only() -> None:
    tenant = Tenant.objects.create(code="HLP-GW3-3", name="Helpdesk GW3 Tenant 3")
    with use_tenant(tenant.id):
        user = UserFactory()
        published = HlpKbArticleFactory(
            tenant=tenant, title="Comment reinitialiser un mot de passe"
        )
        publish_article(published)
        HlpKbArticleFactory(tenant=tenant, title="Article non publie mot de passe")

        rows = _tool_search_kb(tenant, user, query="mot de passe")

    assert len(rows) == 1
    assert rows[0]["id"] == str(published.id)
    assert rows[0]["title"] == published.title
