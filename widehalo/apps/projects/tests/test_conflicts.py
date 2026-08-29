from __future__ import annotations

import datetime as dt

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.projects.services.conflicts import (
    detect_scheduling_conflicts,
    resolve_conflicts_automatically,
)
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def conflict_ctx():
    tenant = Tenant.objects.create(code="PRJ-CONF-T1", name="Projects Conflict Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet avec conflits")
        user = User.objects.create_user(
            email="double-booked@example.com", password="Str0ngPassw0rd!23"
        )
        other_user = User.objects.create_user(
            email="not-conflicted@example.com", password="Str0ngPassw0rd!23"
        )
        yield tenant, project, user, other_user


def test_no_conflict_when_dates_do_not_overlap(conflict_ctx) -> None:
    tenant, project, user, _other = conflict_ctx
    with use_tenant(tenant.id):
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 5),
            duration_days=5,
        )
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 6),
            end_date=dt.date(2026, 1, 10),
            duration_days=5,
        )
        assert detect_scheduling_conflicts(user) == []


def test_conflict_detected_on_overlapping_dates_same_assignee(conflict_ctx) -> None:
    tenant, project, user, _other = conflict_ctx
    with use_tenant(tenant.id):
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 10),
            duration_days=10,
        )
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 1, 8),
            duration_days=4,
        )
        conflicts = detect_scheduling_conflicts(user)
        assert len(conflicts) == 1


def test_task_without_dates_never_triggers_a_false_conflict(conflict_ctx) -> None:
    tenant, project, user, _other = conflict_ctx
    with use_tenant(tenant.id):
        create_task(tenant, project=project, assignee=user)
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 5),
            duration_days=5,
        )
        assert detect_scheduling_conflicts(user) == []


def test_different_assignees_never_conflict(conflict_ctx) -> None:
    tenant, project, user, other_user = conflict_ctx
    with use_tenant(tenant.id):
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 10),
            duration_days=10,
        )
        create_task(
            tenant,
            project=project,
            assignee=other_user,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 1, 8),
            duration_days=4,
        )
        assert detect_scheduling_conflicts(user) == []


def test_resolve_conflicts_automatically_shifts_the_later_task(conflict_ctx) -> None:
    tenant, project, user, _other = conflict_ctx
    with use_tenant(tenant.id):
        first = create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 10),
            duration_days=10,
        )
        second = create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 1, 8),
            duration_days=4,
        )
        resolved = resolve_conflicts_automatically(user)
        assert len(resolved) == 1
        second.refresh_from_db()
        first.refresh_from_db()
        # La 2e tache (start_date la plus tardive) demarre juste apres la fin
        # de la 1re, duree preservee (4 jours).
        assert second.start_date == dt.date(2026, 1, 11)
        assert second.end_date == dt.date(2026, 1, 14)
        assert detect_scheduling_conflicts(user) == []


def test_resolve_conflicts_automatically_cascades_through_a_third_task(conflict_ctx) -> None:
    """Un decalage peut faire apparaitre un nouveau chevauchement avec une
    3e tache — verifie que le service re-detecte apres chaque decalage
    plutot que de travailler sur une liste figee."""
    tenant, project, user, _other = conflict_ctx
    with use_tenant(tenant.id):
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 10),
            duration_days=10,
        )
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 1, 12),
            duration_days=8,
        )
        create_task(
            tenant,
            project=project,
            assignee=user,
            start_date=dt.date(2026, 1, 11),
            end_date=dt.date(2026, 1, 15),
            duration_days=5,
        )
        resolved = resolve_conflicts_automatically(user)
        assert len(resolved) == 2
        assert detect_scheduling_conflicts(user) == []
