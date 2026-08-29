"""AUTO6 — API django-ninja du module `automation`, RBAC restreinte a
`admin`/`direction`. `admin`/`direction` SONT dans `CORE_MFA_REQUIRED_
ROLES`, ce qui bloquerait la connexion JWT de ce test tant qu'un device
TOTP n'est pas enrole (meme constat/meme contournement que
`apps.financing.tests.test_api`/`apps.accounting.tests.test_api`) : groupe
ad hoc portant les permissions `automation` reellement exercees, plutot
que `grant_role("admin")`."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.automation_registry import register_action

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
def api_automation():
    tenant = Tenant.objects.create(code="AUTO-API", name="Automation API Tenant")
    user = User.objects.create_user(
        email="automation-api@example.com", password="Str0ngPassw0rd!23"
    )
    group, _ = Group.objects.get_or_create(name="automation-api-test")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="automation",
            codename__in=[
                "view_autoflow",
                "add_autoflow",
                "change_autoflow",
            ],
        )
    )
    user.groups.add(group)
    return tenant, user


def test_list_actions_endpoint_includes_builtin_notify_role(api_automation) -> None:
    tenant, user = api_automation
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.get("/api/v1/automation/actions", **_headers(token, str(tenant.id)))

    assert response.status_code == 200
    codes = [a["code"] for a in response.json()["results"]]
    assert "core.notify_role" in codes


def test_create_flow_via_api(api_automation) -> None:
    tenant, user = api_automation
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/automation/flows",
        {"name": "Flux API", "trigger_event_type": "workflow.transitioned"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Flux API"
    assert body["is_active"] is False


def test_create_flow_with_unknown_event_type_returns_400(api_automation) -> None:
    tenant, user = api_automation
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/automation/flows",
        {"name": "Flux invalide", "trigger_event_type": "ceci.n_existe_pas"},
        content_type="application/json",
        **_headers(token, str(tenant.id)),
    )

    assert response.status_code == 400


def test_add_action_step_and_activate_and_run_history(api_automation) -> None:
    register_action(
        code="test.api_action",
        module="test",
        label="Action",
        function=lambda tenant_id, params: {"ok": True},
    )
    tenant, user = api_automation
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    flow_response = client.post(
        "/api/v1/automation/flows",
        {"name": "Flux complet", "trigger_event_type": "workflow.transitioned"},
        content_type="application/json",
        **headers,
    )
    flow_id = flow_response.json()["id"]

    step_response = client.post(
        f"/api/v1/automation/flows/{flow_id}/steps/action",
        {"action_code": "test.api_action", "param_mapping": {}},
        content_type="application/json",
        **headers,
    )
    assert step_response.status_code == 200

    activate_response = client.post(
        f"/api/v1/automation/flows/{flow_id}/activate?is_active=true",
        content_type="application/json",
        **headers,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True

    detail_response = client.get(f"/api/v1/automation/flows/{flow_id}", **headers)
    assert detail_response.status_code == 200
    assert len(detail_response.json()["steps"]) == 1

    runs_response = client.get(f"/api/v1/automation/flows/{flow_id}/runs", **headers)
    assert runs_response.status_code == 200
    assert runs_response.json()["results"] == []


def test_save_canvas_via_api_compiles_steps(api_automation) -> None:
    register_action(
        code="test.api_canvas_action",
        module="test",
        label="Action",
        function=lambda tenant_id, params: {"ok": True},
    )
    tenant, user = api_automation
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    flow_response = client.post(
        "/api/v1/automation/flows",
        {"name": "Flux canevas", "trigger_event_type": "workflow.transitioned"},
        content_type="application/json",
        **headers,
    )
    flow_id = flow_response.json()["id"]

    canvas_layout = {
        "drawflow": {
            "Home": {
                "data": {
                    "1": {
                        "id": 1,
                        "data": {
                            "step_type": "action",
                            "action_code": "test.api_canvas_action",
                            "param_mapping": {},
                        },
                        "outputs": {},
                    }
                }
            }
        }
    }
    response = client.post(
        f"/api/v1/automation/flows/{flow_id}/canvas",
        {"canvas_layout": canvas_layout},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200

    detail_response = client.get(f"/api/v1/automation/flows/{flow_id}", **headers)
    assert len(detail_response.json()["steps"]) == 1


def test_endpoints_require_permission(api_automation) -> None:
    """Un utilisateur sans les permissions `automation` recoit 403 — RBAC
    reellement applique, pas seulement disclosed."""
    tenant, _user = api_automation
    other_user = User.objects.create_user(
        email="automation-forbidden@example.com", password="Str0ngPassw0rd!23"
    )
    client = Client()
    token = _access_token(client, other_user.email, "Str0ngPassw0rd!23")

    response = client.get("/api/v1/automation/flows", **_headers(token, str(tenant.id)))
    assert response.status_code == 403
