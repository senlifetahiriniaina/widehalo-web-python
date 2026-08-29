from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.projects.models import PrjTask
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
