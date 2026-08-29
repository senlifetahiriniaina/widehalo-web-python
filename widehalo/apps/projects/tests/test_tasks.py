from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjTask
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import (
    block_task,
    cancel_task,
    create_task,
    finish_task,
    start_task,
    unblock_task,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def project_ctx():
    tenant = Tenant.objects.create(code="PRJ-TASK-T1", name="Projects Task Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet avec taches")
        user = User.objects.create_user(
            email="task-owner@example.com", password="Str0ngPassw0rd!23"
        )
        yield tenant, project, user


def test_create_task_generates_reference_and_defaults(project_ctx) -> None:
    tenant, project, _user = project_ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)
        assert task.reference.startswith("PRJ-TACHE-")
        assert task.task_type == PrjTask.TYPE_TASK
        assert task.state == PrjTask.STATE_TODO
        assert task.percent_complete == 0
        assert task.is_critical_path is False


def test_task_hierarchy_epic_with_task_child_allowed(project_ctx) -> None:
    """Une tache de type `task` peut avoir un parent `epic` (hierarchie
    unifiee, cf. docstring de `apps/projects/models.py`) — la validation
    stricte de coherence des types (epic/task/milestone) est reportee a
    PJ2, seule l'appartenance au meme projet est verifiee ici."""
    tenant, project, _user = project_ctx
    with use_tenant(tenant.id):
        epic = create_task(tenant, project=project, task_type=PrjTask.TYPE_EPIC)
        task = create_task(tenant, project=project, task_type=PrjTask.TYPE_TASK, parent=epic)
        assert task.parent_id == epic.id
        assert epic.children.get(id=task.id) == task


def test_task_parent_must_belong_to_same_project(project_ctx) -> None:
    tenant, project, _user = project_ctx
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Autre projet")
        epic = create_task(tenant, project=other_project, task_type=PrjTask.TYPE_EPIC)
        with pytest.raises(ValidationError):
            create_task(tenant, project=project, task_type=PrjTask.TYPE_TASK, parent=epic)


def test_task_workflow_happy_path(project_ctx) -> None:
    tenant, project, user = project_ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)

        start_task(task, user)
        task.refresh_from_db()
        assert task.state == PrjTask.STATE_IN_PROGRESS

        block_task(task, user)
        task.refresh_from_db()
        assert task.state == PrjTask.STATE_BLOCKED

        unblock_task(task, user)
        task.refresh_from_db()
        assert task.state == PrjTask.STATE_IN_PROGRESS

        finish_task(task, user)
        task.refresh_from_db()
        assert task.state == PrjTask.STATE_DONE
        assert task.percent_complete == 100


def test_task_cancel_from_todo(project_ctx) -> None:
    tenant, project, user = project_ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)
        cancel_task(task, user)
        task.refresh_from_db()
        assert task.state == PrjTask.STATE_CANCELLED


def test_task_forbidden_transition_from_done_raises(project_ctx) -> None:
    """Un chemin interdit (ex. reprendre une tache deja `done`) doit
    echouer via `attempt_transition()` — jamais silencieusement ignore."""
    tenant, project, user = project_ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)
        start_task(task, user)
        finish_task(task, user)
        task.refresh_from_db()
        with pytest.raises(TransitionPermissionError):
            start_task(task, user)
        task.refresh_from_db()
        assert task.state == PrjTask.STATE_DONE


def test_task_transition_persists_state_after_reload(project_ctx) -> None:
    """Non-regression du piege documente : `attempt_transition()` ne
    sauvegarde jamais lui-meme — la fonction de service DOIT persister
    l'etat, sans quoi il disparaitrait au rechargement depuis la base."""
    tenant, project, user = project_ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)
        start_task(task, user)

        reloaded = PrjTask.objects.get(id=task.id)
        assert reloaded.state == PrjTask.STATE_IN_PROGRESS
