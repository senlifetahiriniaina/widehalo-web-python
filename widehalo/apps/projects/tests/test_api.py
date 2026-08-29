from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_projects():
    # `resp_commercial` porte la gestion de projet (cf. plan RBAC) et
    # n'est PAS dans `CORE_MFA_REQUIRED_ROLES` — pas de contournement JWT
    # necessaire, contrairement a `financing` (`admin`/`direction`/
    # `comptable`), cf. commentaire de `apps.financing.tests.test_api`.
    tenant = Tenant.objects.create(code="PRJ-API", name="Projects API Tenant")
    user = User.objects.create_user(email="projects-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")
    return tenant, user


def test_create_and_read_project_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet API"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200, response.content
    project_id = response.json()["id"]

    response = client.get(f"/api/v1/projects/{project_id}", **_headers(token, str(tenant.id)))
    assert response.status_code == 200
    assert response.json()["name"] == "Projet API"
    assert response.json()["tasks"] == []


def test_create_task_and_transition_via_api(api_projects) -> None:
    tenant, user = api_projects
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/projects",
        {"name": "Projet avec tache API"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    project_id = response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        {"task_type": "task"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200, response.content
    task_id = response.json()["id"]
    assert response.json()["state"] == "todo"

    response = client.post(
        f"/api/v1/projects/tasks/{task_id}/transition/start",
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )
    assert response.status_code == 200, response.content
    assert response.json()["state"] == "in_progress"


def test_unauthenticated_request_is_rejected() -> None:
    client = Client()
    response = client.get("/api/v1/projects")
    assert response.status_code == 401
