"""Tests PJ6 (sprints agiles, `services/sprints.py`) — cf. plan, section
« Module `projects` », etape PJ6."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import StateTransitionLog
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjSprint, PrjTask
from apps.projects.services.projects import create_project
from apps.projects.services.sprints import (
    complete_sprint,
    compute_burndown,
    compute_velocity,
    create_sprint,
    get_backlog,
    start_sprint,
)
from apps.projects.services.tasks import create_task, finish_task, start_task
from apps.projects.tests.factories import PrjSprintFactory, PrjTaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def sprint_ctx():
    tenant = Tenant.objects.create(code="PRJ-SPRINT", name="Projects Sprint Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet agile")
        user = User.objects.create_user(
            email="sprint-owner@example.com", password="Str0ngPassw0rd!23"
        )
        yield tenant, project, user


# --- create_sprint / start_sprint --------------------------------------------------


def test_create_sprint_rejects_end_before_start(sprint_ctx) -> None:
    tenant, project, _user = sprint_ctx
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_sprint(
            project,
            name="Sprint invalide",
            start_date=dt.date(2026, 1, 10),
            end_date=dt.date(2026, 1, 1),
        )


def test_only_one_active_sprint_per_project(sprint_ctx) -> None:
    """Regle metier : un seul sprint actif a la fois par projet — demarrer
    un second sprint pendant qu'un premier est deja actif est REFUSE
    explicitement (ValidationError), pas une bascule silencieuse."""
    tenant, project, _user = sprint_ctx
    with use_tenant(tenant.id):
        sprint_1 = create_sprint(
            project, name="Sprint 1", start_date=dt.date(2026, 1, 1), end_date=dt.date(2026, 1, 14)
        )
        sprint_2 = create_sprint(
            project, name="Sprint 2", start_date=dt.date(2026, 1, 15), end_date=dt.date(2026, 1, 28)
        )
        start_sprint(sprint_1)
        sprint_1.refresh_from_db()
        assert sprint_1.status == PrjSprint.STATUS_ACTIVE

        with pytest.raises(ValidationError):
            start_sprint(sprint_2)
        sprint_2.refresh_from_db()
        assert sprint_2.status == PrjSprint.STATUS_PLANNED


def test_complete_sprint_detaches_unfinished_tasks(sprint_ctx) -> None:
    """`complete_sprint` : les taches non `done`/`cancelled` sont detachees
    du sprint (`sprint=None`, retour au backlog) — cf. decision disclosee
    dans `services/sprints.py`. Une tache deja `done` reste rattachee
    (necessaire a `compute_velocity`)."""
    tenant, project, user = sprint_ctx
    with use_tenant(tenant.id):
        sprint = create_sprint(
            project, name="Sprint X", start_date=dt.date(2026, 2, 1), end_date=dt.date(2026, 2, 14)
        )
        unfinished = create_task(tenant, project=project, story_points=3)
        unfinished.sprint = sprint
        unfinished.save(update_fields=["sprint"])

        finished = create_task(tenant, project=project, story_points=5)
        finished.sprint = sprint
        finished.save(update_fields=["sprint"])
        start_task(finished, user)
        finish_task(finished, user)

        complete_sprint(sprint)
        sprint.refresh_from_db()
        unfinished.refresh_from_db()
        finished.refresh_from_db()

        assert sprint.status == PrjSprint.STATUS_COMPLETED
        assert unfinished.sprint_id is None
        assert finished.sprint_id == sprint.id


# --- get_backlog -------------------------------------------------------------------


def test_backlog_excludes_sprinted_and_terminal_tasks(sprint_ctx) -> None:
    tenant, project, user = sprint_ctx
    with use_tenant(tenant.id):
        sprint = create_sprint(
            project, name="Sprint B", start_date=dt.date(2026, 3, 1), end_date=dt.date(2026, 3, 14)
        )
        backlog_task = create_task(tenant, project=project, story_points=2)
        sprinted_task = create_task(tenant, project=project, story_points=3)
        sprinted_task.sprint = sprint
        sprinted_task.save(update_fields=["sprint"])
        cancelled_task = create_task(tenant, project=project, story_points=1)
        cancelled_task.cancel()
        cancelled_task.save(update_fields=["state"])

        backlog_ids = {t.id for t in get_backlog(project)}
        assert backlog_ids == {backlog_task.id}


# --- compute_burndown ---------------------------------------------------------------


def _backdate_task_creation(task: PrjTask, day: dt.date) -> None:
    PrjTask.objects.filter(id=task.id).update(
        created_at=timezone.make_aware(dt.datetime.combine(day, dt.time(0, 0)))
    )


def _set_transition_log_date(task: PrjTask, to_state: str, day: dt.date) -> None:
    content_type = ContentType.objects.get_for_model(PrjTask)
    StateTransitionLog.objects.filter(
        content_type=content_type, object_id=str(task.id), to_state=to_state
    ).update(created_at=timezone.make_aware(dt.datetime.combine(day, dt.time(9, 0))))


def test_compute_burndown_uses_state_transition_history(sprint_ctx) -> None:
    """Cas verifie a la main (cf. docstring de `compute_burndown`) : sprint
    de 3 jours (day0/day1/day2). Tache A (4 points) reste `todo` toute la
    periode -> compte tous les jours. Tache B (6 points) passe `done` le
    day1 (log de transition recale a cette date) -> ne compte plus a partir
    du day1. Attendu : [10, 4, 4]."""
    tenant, project, user = sprint_ctx
    day0 = dt.date(2026, 4, 6)
    day1 = day0 + dt.timedelta(days=1)
    day2 = day0 + dt.timedelta(days=2)
    with use_tenant(tenant.id):
        sprint = create_sprint(project, name="Sprint burndown", start_date=day0, end_date=day2)

        task_a = create_task(tenant, project=project, story_points=4)
        task_a.sprint = sprint
        task_a.save(update_fields=["sprint"])
        _backdate_task_creation(task_a, day0 - dt.timedelta(days=1))

        task_b = create_task(tenant, project=project, story_points=6)
        task_b.sprint = sprint
        task_b.save(update_fields=["sprint"])
        _backdate_task_creation(task_b, day0 - dt.timedelta(days=1))
        start_task(task_b, user)
        finish_task(task_b, user)
        _set_transition_log_date(task_b, PrjTask.STATE_IN_PROGRESS, day0)
        _set_transition_log_date(task_b, PrjTask.STATE_DONE, day1)

        burndown = compute_burndown(sprint)

    assert [point["date"] for point in burndown] == [day0, day1, day2]
    assert [point["story_points_remaining"] for point in burndown] == [
        Decimal("10"),
        Decimal("4"),
        Decimal("4"),
    ]


def test_compute_burndown_ignores_task_without_story_points(sprint_ctx) -> None:
    tenant, project, _user = sprint_ctx
    day0 = dt.date(2026, 5, 1)
    with use_tenant(tenant.id):
        sprint = create_sprint(project, name="Sprint vide", start_date=day0, end_date=day0)
        task = create_task(tenant, project=project)  # story_points=None
        task.sprint = sprint
        task.save(update_fields=["sprint"])
        _backdate_task_creation(task, day0)

        burndown = compute_burndown(sprint)

    assert burndown == [{"date": day0, "story_points_remaining": Decimal("0")}]


# --- compute_velocity ----------------------------------------------------------------


def test_compute_velocity_averages_completed_sprints(sprint_ctx) -> None:
    """Cas verifie a la main : 2 sprints `completed`, l'un avec 8 points
    `done`, l'autre avec 4 -> velocite = (8 + 4) / 2 = 6."""
    tenant, project, _user = sprint_ctx
    with use_tenant(tenant.id):
        sprint_1 = PrjSprintFactory(
            tenant=tenant,
            project=project,
            status=PrjSprint.STATUS_COMPLETED,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 14),
        )
        PrjTaskFactory(
            tenant=tenant,
            project=project,
            sprint=sprint_1,
            state=PrjTask.STATE_DONE,
            story_points=5,
        )
        PrjTaskFactory(
            tenant=tenant,
            project=project,
            sprint=sprint_1,
            state=PrjTask.STATE_DONE,
            story_points=3,
        )
        # Tache non terminee du meme sprint : ne doit PAS compter.
        PrjTaskFactory(
            tenant=tenant,
            project=project,
            sprint=sprint_1,
            state=PrjTask.STATE_IN_PROGRESS,
            story_points=99,
        )

        sprint_2 = PrjSprintFactory(
            tenant=tenant,
            project=project,
            status=PrjSprint.STATUS_COMPLETED,
            start_date=dt.date(2026, 1, 15),
            end_date=dt.date(2026, 1, 28),
        )
        PrjTaskFactory(
            tenant=tenant,
            project=project,
            sprint=sprint_2,
            state=PrjTask.STATE_DONE,
            story_points=4,
        )

        # Sprint encore planifie : ne doit pas entrer dans le calcul.
        sprint_3 = PrjSprintFactory(
            tenant=tenant,
            project=project,
            status=PrjSprint.STATUS_PLANNED,
            start_date=dt.date(2026, 2, 1),
            end_date=dt.date(2026, 2, 14),
        )
        PrjTaskFactory(
            tenant=tenant,
            project=project,
            sprint=sprint_3,
            state=PrjTask.STATE_DONE,
            story_points=100,
        )

        velocity = compute_velocity(project)

    assert velocity == Decimal("6.00")


def test_compute_velocity_with_no_completed_sprint_is_zero(sprint_ctx) -> None:
    tenant, project, _user = sprint_ctx
    with use_tenant(tenant.id):
        velocity = compute_velocity(project)
    assert velocity == Decimal("0")
