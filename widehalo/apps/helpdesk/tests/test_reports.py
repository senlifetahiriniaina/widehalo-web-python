"""HD4 : tests des rapports `services.reports` — calcul manuel de reference
documente dans chaque test, verifie EXACTEMENT contre le resultat renvoye
par la fonction (meme rigueur que `apps.projects.tests.test_evm`)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import KIND_INCIDENT, HlpSlaBreach, HlpTicket
from apps.helpdesk.services.csat import submit_csat_response
from apps.helpdesk.services.reports import (
    agent_performance_report,
    csat_summary,
    sla_compliance_report,
    team_benchmark_report,
)
from apps.helpdesk.services.tickets import (
    assign_ticket,
    close_ticket,
    create_ticket,
    resolve_ticket,
)
from apps.helpdesk.tests.factories import HlpSlaPolicyFactory, HlpTeamFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_and_users():
    tenant = Tenant.objects.create(code="HLP-RPT", name="Helpdesk Reports Tenant")
    with use_tenant(tenant.id):
        requester = UserFactory()
        agent_a = UserFactory()
        agent_b = UserFactory()
        yield tenant, requester, agent_a, agent_b


def test_csat_summary_manual_calculation(tenant_and_users) -> None:
    """3 tickets resolus/clotures sur la periode, 2 reponses CSAT (notes 4
    et 2) :
    - moyenne = (4 + 2) / 2 = 3.0
    - distribution = {"1": 0, "2": 1, "3": 0, "4": 1, "5": 0}
    - nombre de reponses = 2
    - taux de reponse = 2 / 3 (2 reponses sur 3 tickets resolus/clotures)."""
    tenant, requester, agent_a, agent_b = tenant_and_users
    with use_tenant(tenant.id):
        t1 = create_ticket(tenant, subject="T1", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(t1, agent_a, assignee=agent_a)
        resolve_ticket(t1, agent_a)
        submit_csat_response(t1, score=4)

        t2 = create_ticket(tenant, subject="T2", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(t2, agent_a, assignee=agent_a)
        resolve_ticket(t2, agent_a)
        close_ticket(t2, agent_a)
        submit_csat_response(t2, score=2)

        t3 = create_ticket(tenant, subject="T3", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(t3, agent_a, assignee=agent_a)
        resolve_ticket(t3, agent_a)
        # t3 : aucune reponse CSAT.

        result = csat_summary(tenant)

        assert result["average_score"] == 3.0
        assert result["score_distribution"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 0}
        assert result["response_count"] == 2
        assert result["resolved_or_closed_count"] == 3
        assert result["response_rate"] == pytest.approx(2 / 3)


def test_agent_performance_report_manual_calculation(tenant_and_users) -> None:
    """agent_a : 2 tickets assignes, 1 resolu -> taux de resolution 0.5.
    Premiere reponse : seul le ticket resolu a `first_responded_at` positionne
    (via un commentaire non-interne d'un tiers) 30 minutes apres creation ;
    l'autre ticket n'a pas de premiere reponse -> moyenne = 30 minutes
    (calculee sur le SEUL ticket renseigne, cf. docstring du service).
    `resolved_at` est positionne par `resolve_ticket` a `timezone.now()`,
    quasi-instantane apres `created_at` en execution de test -> duree de
    resolution moyenne ~0 minute (PAS `None` : `resolved_at` EST renseigne,
    contrairement a `first_responded_at` sur `t2`).
    agent_b : 1 ticket assigne, 0 resolu -> taux de resolution 0.0, aucun
    horodatage renseigne -> les deux moyennes de duree sont `None`."""
    tenant, requester, agent_a, agent_b = tenant_and_users
    with use_tenant(tenant.id):
        from apps.helpdesk.services.tickets import add_comment

        t1 = create_ticket(tenant, subject="T1", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(t1, agent_a, assignee=agent_a)
        add_comment(t1, author=agent_a, body="Bien recu.")
        resolve_ticket(t1, agent_a)
        # `first_responded_at` a ete positionne a `timezone.now()` par
        # `add_comment` (juste avant `resolve_ticket`) : on le force
        # explicitement a +30 minutes apres `created_at` pour un calcul
        # manuel exact et deterministe (independant du temps reel ecoule
        # pendant l'execution du test).
        t1.first_responded_at = t1.created_at + timedelta(minutes=30)
        t1.save(update_fields=["first_responded_at"])

        t2 = create_ticket(tenant, subject="T2", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(t2, agent_a, assignee=agent_a)
        # t2 reste "in_progress", jamais resolu, jamais de premiere reponse.

        t3 = create_ticket(tenant, subject="T3", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(t3, agent_b, assignee=agent_b)
        # t3 reste "in_progress".

        rows = {row["assignee_id"]: row for row in agent_performance_report(tenant)}

        row_a = rows[str(agent_a.id)]
        assert row_a["ticket_count"] == 2
        assert row_a["resolved_or_closed_count"] == 1
        assert row_a["resolution_rate"] == pytest.approx(0.5)
        assert row_a["avg_first_response_minutes"] == pytest.approx(30.0)
        assert row_a["avg_resolution_minutes"] == pytest.approx(0.0, abs=1.0)

        row_b = rows[str(agent_b.id)]
        assert row_b["ticket_count"] == 1
        assert row_b["resolved_or_closed_count"] == 0
        assert row_b["resolution_rate"] == 0.0
        assert row_b["avg_first_response_minutes"] is None
        assert row_b["avg_resolution_minutes"] is None


def test_team_benchmark_report_groups_by_team(tenant_and_users) -> None:
    """2 tickets pour la meme equipe, 1 resolu -> taux de resolution 0.5."""
    tenant, requester, agent_a, agent_b = tenant_and_users
    with use_tenant(tenant.id):
        team = HlpTeamFactory(tenant=tenant)

        t1 = create_ticket(tenant, subject="T1", requester=requester, kind=KIND_INCIDENT, team=team)
        assign_ticket(t1, agent_a, assignee=agent_a)
        resolve_ticket(t1, agent_a)

        t2 = create_ticket(tenant, subject="T2", requester=requester, kind=KIND_INCIDENT, team=team)
        assign_ticket(t2, agent_b, assignee=agent_b)
        # t2 reste "in_progress".

        rows = team_benchmark_report(tenant)

        assert len(rows) == 1
        assert rows[0]["team_id"] == str(team.id)
        assert rows[0]["team_label"] == team.name
        assert rows[0]["ticket_count"] == 2
        assert rows[0]["resolved_or_closed_count"] == 1
        assert rows[0]["resolution_rate"] == pytest.approx(0.5)


def test_sla_compliance_report_manual_calculation(tenant_and_users) -> None:
    """2 tickets avec politique SLA, dont un en breche de premiere reponse
    (echeance forcee dans le passe) :
    - total = 2
    - breach_count = 1 (breach_type="first_response")
    - compliance_rate = 1 - 1/2 = 0.5."""
    tenant, requester, agent_a, agent_b = tenant_and_users
    with use_tenant(tenant.id):
        from apps.helpdesk.services.sla import check_breaches

        policy = HlpSlaPolicyFactory(
            tenant=tenant, first_response_minutes=30, resolution_minutes=480
        )

        t1 = create_ticket(
            tenant, subject="T1", requester=requester, kind=KIND_INCIDENT, sla_policy=policy
        )
        t1.first_response_due_at = timezone.now() - timedelta(minutes=5)
        t1.save(update_fields=["first_response_due_at"])

        create_ticket(
            tenant, subject="T2", requester=requester, kind=KIND_INCIDENT, sla_policy=policy
        )

        check_breaches(tenant)  # cree la breche pour t1

        result = sla_compliance_report(tenant)

        assert result["total_tickets_with_sla"] == 2
        assert result["breach_count"] == 1
        assert result["breaches_by_type"][HlpSlaBreach.BREACH_FIRST_RESPONSE] == 1
        assert result["breaches_by_type"][HlpSlaBreach.BREACH_RESOLUTION] == 0
        assert result["compliance_rate"] == pytest.approx(0.5)


def test_sla_compliance_report_no_tickets_returns_none_rate(tenant_and_users) -> None:
    tenant, requester, agent_a, agent_b = tenant_and_users
    with use_tenant(tenant.id):
        result = sla_compliance_report(tenant)
        assert result["total_tickets_with_sla"] == 0
        assert result["compliance_rate"] is None


def test_date_range_excludes_tickets_outside_window(tenant_and_users) -> None:
    """Un ticket cree il y a 60 jours, resolu, est EXCLU d'une fenetre de
    30 jours glissants — verifie via `agent_performance_report` (le
    `ticket_count` de l'agent ne doit compter QUE le ticket recent)."""
    tenant, requester, agent_a, agent_b = tenant_and_users
    with use_tenant(tenant.id):
        old_ticket = create_ticket(tenant, subject="Old", requester=requester, kind=KIND_INCIDENT)
        assign_ticket(old_ticket, agent_a, assignee=agent_a)
        resolve_ticket(old_ticket, agent_a)
        HlpTicket.objects.filter(id=old_ticket.id).update(
            created_at=timezone.now() - timedelta(days=60)
        )

        recent_ticket = create_ticket(
            tenant, subject="Recent", requester=requester, kind=KIND_INCIDENT
        )
        assign_ticket(recent_ticket, agent_a, assignee=agent_a)

        today = timezone.now().date()
        rows = {
            row["assignee_id"]: row
            for row in agent_performance_report(
                tenant, date_from=today - timedelta(days=30), date_to=today
            )
        }

        assert rows[str(agent_a.id)]["ticket_count"] == 1

        # Sans borne de date, les DEUX tickets sont comptes.
        rows_unbounded = {row["assignee_id"]: row for row in agent_performance_report(tenant)}
        assert rows_unbounded[str(agent_a.id)]["ticket_count"] == 2
