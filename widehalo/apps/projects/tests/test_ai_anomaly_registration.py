"""AI3 : adaptateur `apps.projects.services.ai_anomaly_registration` —
verifie que le check REEL surfacce un veritable chevauchement de dates
entre deux taches affectees au meme utilisateur, en reutilisant
`services.conflicts.detect_scheduling_conflicts` (PJ3, deja construit)."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.anomaly_registry import SEVERITY_MEDIUM, get_anomaly_check
from apps.core.tests.utils import use_tenant
from apps.projects.services.ai_anomaly_registration import _check_scheduling_conflicts
from apps.projects.tests.factories import PrjTaskFactory, PrjTeamMemberFactory

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("projects.scheduling_conflict")
    assert registered is not None
    assert registered.module == "projects"
    assert registered.function is _check_scheduling_conflicts


def test_check_surfaces_a_real_overlap_between_two_tasks_of_a_team_member() -> None:
    tenant = Tenant.objects.create(code="PRJ-AI3", name="Projects AI3 Tenant")
    with use_tenant(tenant.id):
        team_member = PrjTeamMemberFactory(tenant=tenant)
        user = team_member.user

        PrjTaskFactory(
            tenant=tenant,
            project=team_member.project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 10),
            duration_days=10,
        )
        PrjTaskFactory(
            tenant=tenant,
            project=team_member.project,
            assignee=user,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 1, 15),
            duration_days=11,
        )

        candidates = _check_scheduling_conflicts(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].content_type_label == "projects.prjtask"
    assert candidates[0].severity == SEVERITY_MEDIUM


def test_check_returns_nothing_without_any_overlap() -> None:
    tenant = Tenant.objects.create(code="PRJ-AI3-OK", name="Projects AI3 OK Tenant")
    with use_tenant(tenant.id):
        team_member = PrjTeamMemberFactory(tenant=tenant)
        user = team_member.user

        PrjTaskFactory(
            tenant=tenant,
            project=team_member.project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 5),
            duration_days=5,
        )
        PrjTaskFactory(
            tenant=tenant,
            project=team_member.project,
            assignee=user,
            start_date=dt.date(2026, 2, 1),
            end_date=dt.date(2026, 2, 5),
            duration_days=5,
        )

        candidates = _check_scheduling_conflicts(str(tenant.id))

    assert candidates == []
