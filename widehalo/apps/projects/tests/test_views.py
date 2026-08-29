from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.projects.models import PrjTask
from apps.projects.services.dependencies import add_dependency
from apps.projects.services.evm import add_budget_line
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

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
