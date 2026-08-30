"""HD5 : `services.ai_insight_registration` — insight de tendance de
backlog, jamais fabrique sans une croissance nette reelle et non triviale."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.insight_source_registry import get_insight_source
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.services.ai_insight_registration import _backlog_trend_insight
from apps.helpdesk.services.tickets import create_ticket

pytestmark = pytest.mark.django_db


def test_source_is_registered_in_the_shared_registry() -> None:
    registered = get_insight_source("helpdesk.ticket_backlog_trend")
    assert registered is not None
    assert registered.module == "helpdesk"
    assert registered.function is _backlog_trend_insight


def test_no_insight_when_backlog_is_stable() -> None:
    tenant = Tenant.objects.create(code="HLP-AI5-1", name="Helpdesk AI5 Tenant 1")
    with use_tenant(tenant.id):
        requester = UserFactory()
        create_ticket(tenant, subject="Ticket calme", requester=requester)

        candidates = _backlog_trend_insight(str(tenant.id))

    assert candidates == []


def test_insight_fires_on_meaningful_backlog_growth() -> None:
    tenant = Tenant.objects.create(code="HLP-AI5-2", name="Helpdesk AI5 Tenant 2")
    with use_tenant(tenant.id):
        requester = UserFactory()
        for _i in range(4):
            create_ticket(tenant, subject="Ticket recent", requester=requester)

        candidates = _backlog_trend_insight(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.category == "helpdesk"
    assert candidate.source_modules == ["helpdesk"]
    assert "4" in candidate.body
