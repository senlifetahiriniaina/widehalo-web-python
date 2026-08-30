"""HD2 : tests de `services.sla.check_breaches` — idempotence (jamais un
doublon au deuxieme passage) et detection stricte (seule une echeance
reellement depassee cree une breche)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import KIND_INCIDENT, HlpSlaBreach, HlpTicket
from apps.helpdesk.services.sla import check_breaches
from apps.helpdesk.services.tickets import create_ticket
from apps.helpdesk.tests.factories import HlpSlaPolicyFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_agent():
    tenant = Tenant.objects.create(code="HLP-SLA", name="Helpdesk SLA Tenant")
    with use_tenant(tenant.id):
        agent = UserFactory()
        yield tenant, agent


def test_check_breaches_creates_breach_when_due_date_passed(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=30, resolution_minutes=60
        )
        ticket = create_ticket(
            tenant, subject="Test", requester=agent, kind=KIND_INCIDENT, sla_policy=policy
        )
        # Fait reculer artificiellement les echeances dans le passe (seul
        # moyen deterministe de simuler "le temps s'est ecoule" sans
        # attendre reellement en test).
        ticket.first_response_due_at = timezone.now() - timedelta(minutes=5)
        ticket.resolution_due_at = timezone.now() + timedelta(hours=1)
        ticket.save(update_fields=["first_response_due_at", "resolution_due_at"])

        breaches = check_breaches(tenant)

        assert len(breaches) == 1
        assert breaches[0].breach_type == HlpSlaBreach.BREACH_FIRST_RESPONSE
        assert HlpSlaBreach.objects.filter(ticket=ticket).count() == 1


def test_check_breaches_is_idempotent(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=30, resolution_minutes=60
        )
        ticket = create_ticket(
            tenant, subject="Test", requester=agent, kind=KIND_INCIDENT, sla_policy=policy
        )
        ticket.first_response_due_at = timezone.now() - timedelta(minutes=5)
        ticket.resolution_due_at = timezone.now() - timedelta(minutes=1)
        ticket.save(update_fields=["first_response_due_at", "resolution_due_at"])

        first_run = check_breaches(tenant)
        second_run = check_breaches(tenant)

        assert len(first_run) == 2  # premiere reponse ET resolution en retard
        assert len(second_run) == 0  # rien de nouveau au deuxieme passage
        assert HlpSlaBreach.objects.filter(ticket=ticket).count() == 2


def test_check_breaches_does_not_flag_future_due_dates(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=60, resolution_minutes=480
        )
        create_ticket(
            tenant, subject="Test", requester=agent, kind=KIND_INCIDENT, sla_policy=policy
        )

        breaches = check_breaches(tenant)

        assert breaches == []
        assert HlpSlaBreach.objects.count() == 0


def test_check_breaches_updates_risk_score(tenant_and_agent) -> None:
    tenant, agent = tenant_and_agent
    with use_tenant(tenant.id):
        policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=30, resolution_minutes=60
        )
        ticket = create_ticket(
            tenant, subject="Test", requester=agent, kind=KIND_INCIDENT, sla_policy=policy
        )
        ticket.resolution_due_at = timezone.now() - timedelta(hours=1)
        ticket.save(update_fields=["resolution_due_at"])

        check_breaches(tenant)

        reloaded = HlpTicket.objects.get(id=ticket.id)
        assert reloaded.risk_score > 0
