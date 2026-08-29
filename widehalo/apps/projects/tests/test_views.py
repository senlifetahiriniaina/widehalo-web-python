from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.projects.models import PrjTask
from apps.projects.services.capacity import add_team_member
from apps.projects.services.dependencies import add_dependency
from apps.projects.services.evm import add_budget_line
from apps.projects.services.projects import create_project
from apps.projects.services.sprints import create_sprint
from apps.projects.services.tasks import create_task, start_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_projects():
    tenant = Tenant.objects.create(code="PRJ-WEB", name="Projects Web Tenant")
    user = User.objects.create_user(email="projects-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "collaborateur")
    return tenant, user


def test_project_list_screen_renders(web_projects) -> None:
    tenant, user = web_projects
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/projects/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_project_create_screen_renders(web_projects) -> None:
    tenant, user = web_projects
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/projects/new/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_project_detail_screen_renders_with_tasks(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet ecran")
        create_task(tenant, project=project, task_type=PrjTask.TYPE_TASK)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert b"Projet ecran" in response.content


def test_project_detail_add_task_and_start_it(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet formulaire")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/projects/{project.id}/",
        {"action": "add_task", "task_type": PrjTask.TYPE_TASK},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        task = project.tasks.get()
        assert task.task_type == PrjTask.TYPE_TASK

    response = client.post(
        f"/projects/{project.id}/",
        {"action": "start", "task_id": str(task.id)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.state == PrjTask.STATE_IN_PROGRESS


def test_project_gantt_screen_renders_svg(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet Gantt ecran")
        task_a = create_task(
            tenant, project=project, start_date=dt.date(2026, 3, 1), duration_days=4
        )
        task_b = create_task(tenant, project=project, duration_days=2)
        add_dependency(task_a, task_b)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/gantt/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert b"<svg" in response.content
    assert b"gantt-dependency" in response.content


def test_project_gantt_screen_updates_dates_via_form_and_recomputes_critical_path(
    web_projects,
) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet Gantt formulaire")
        task_a = create_task(
            tenant, project=project, start_date=dt.date(2026, 4, 1), duration_days=3
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/projects/{project.id}/gantt/",
        {
            "task_id": str(task_a.id),
            "start_date": "2026-04-05",
            "end_date": "",
            "duration_days": "6",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        task_a.refresh_from_db()
        assert task_a.start_date == dt.date(2026, 4, 5)
        assert task_a.duration_days == 6
        assert task_a.is_critical_path is True


def test_project_budget_screen_renders_lines_and_evm_indicators(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(
            tenant,
            name="Projet ecran budget",
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 11),
        )
        add_budget_line(
            project,
            category="capex",
            label="Materiel",
            planned_amount=Decimal("1000"),
            actual_amount=Decimal("500"),
            period=dt.date(2026, 1, 5),
        )
        task = create_task(tenant, project=project, duration_days=1)
        task.percent_complete = 50
        task.save(update_fields=["percent_complete"])
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/budget/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert b"Materiel" in response.content


def test_project_budget_screen_adds_budget_line_via_form(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet formulaire budget")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/projects/{project.id}/budget/",
        {
            "category": "opex",
            "label": "Prestation",
            "planned_amount": "200",
            "actual_amount": "0",
            "period": "2026-02-01",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        line = project.budget_lines.get()
        assert line.label == "Prestation"
        assert line.planned_amount == Decimal("200.0000")


# --- PJ6 : sprints/backlog/burndown/Kanban/Calendrier/Roadmap -----------------------


def test_project_sprints_screen_creates_and_starts_sprint(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet sprints ecran")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/projects/{project.id}/sprints/",
        {
            "action": "create",
            "name": "Sprint 1",
            "start_date": "2026-06-01",
            "end_date": "2026-06-14",
            "goal": "Livrer le MVP",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        sprint = project.sprints.get()
        assert sprint.name == "Sprint 1"

    response = client.post(
        f"/projects/{project.id}/sprints/",
        {"action": "start", "sprint_id": str(sprint.id)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    sprint.refresh_from_db()
    assert sprint.status == "active"


def test_project_backlog_screen_lists_unassigned_tasks(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet backlog ecran")
        task = create_task(tenant, project=project, story_points=3)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/backlog/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert task.reference.encode() in response.content


def test_project_kanban_screen_groups_tasks_by_state(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet kanban ecran")
        todo_task = create_task(tenant, project=project)
        in_progress_task = create_task(tenant, project=project)
        start_task(in_progress_task, user)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/kanban/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert todo_task.reference.encode() in response.content
    assert in_progress_task.reference.encode() in response.content


def test_project_calendar_screen_groups_tasks_by_month(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet calendrier ecran")
        dated_task = create_task(tenant, project=project, start_date=dt.date(2026, 7, 3))
        create_task(tenant, project=project)  # sans date : absente du calendrier
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/calendar/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert b"2026-07" in response.content
    assert dated_task.reference.encode() in response.content


def test_project_roadmap_screen_lists_epics_and_milestones_only(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet roadmap ecran")
        epic = create_task(
            tenant, project=project, task_type=PrjTask.TYPE_EPIC, start_date=dt.date(2026, 8, 1)
        )
        milestone = create_task(
            tenant,
            project=project,
            task_type=PrjTask.TYPE_MILESTONE,
            start_date=dt.date(2026, 9, 1),
        )
        plain_task = create_task(tenant, project=project, task_type=PrjTask.TYPE_TASK)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/projects/{project.id}/roadmap/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert epic.reference.encode() in response.content
    assert milestone.reference.encode() in response.content
    assert plain_task.reference.encode() not in response.content


def test_project_sprint_burndown_screen_renders(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet burndown ecran")
        sprint = create_sprint(
            project,
            name="Sprint ecran",
            start_date=dt.date(2026, 10, 1),
            end_date=dt.date(2026, 10, 3),
        )
        task = create_task(tenant, project=project, story_points=5)
        task.sprint = sprint
        task.save(update_fields=["sprint"])
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(
        f"/projects/{project.id}/sprints/{sprint.id}/burndown/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert response.status_code == 200
    assert b"2026-10-01" in response.content


def test_project_team_screen_add_and_remove_member(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet equipe ecran")
        member_user = User.objects.create_user(
            email="team-view-member@example.com", password="Str0ngPassw0rd!23"
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/projects/{project.id}/team/",
        {
            "action": "add",
            "user_id": str(member_user.id),
            "role": "developpeur",
            "allocation_pct": "40",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    assert b"40%" in response.content

    with use_tenant(tenant.id):
        member_id = str(project.team_members.get(user=member_user).id)

    response = client.post(
        f"/projects/{project.id}/team/",
        {"action": "remove", "member_id": member_id},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    assert b"Aucun membre." in response.content


def test_user_capacity_heatmap_screen_renders(web_projects) -> None:
    tenant, user = web_projects
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet heatmap ecran")
        add_team_member(project, user, allocation_pct=70)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(
        f"/projects/users/{user.id}/capacity-heatmap/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert response.status_code == 200
    assert b"70%" in response.content


def test_config_custom_fields_screen_create(web_projects) -> None:
    tenant, user = web_projects
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        "/projects/config/custom-fields/",
        {
            "entity_type": "task",
            "field_key": "budget_code",
            "field_label": "Code budgetaire",
            "field_type": "text",
            "required": "on",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    assert b"budget_code" in response.content
