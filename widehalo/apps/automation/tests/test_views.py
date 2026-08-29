"""AUTO5/AUTO6 — ecrans HTMX minimaux du module `automation` : rendu de
la liste, du formulaire de creation, du constructeur (canevas) et de
l'historique d'execution. Meme discipline que
`apps.financing.tests.test_views`/`apps.strategy.tests.test_views` : les
vues HTMX ne verifient que `@login_required`, pas de RBAC N2 (deja
verifie au niveau API django-ninja), donc un role sans MFA suffit ici."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.automation.services.flows import add_action_step, create_flow
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.automation_registry import register_action
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_automation():
    tenant = Tenant.objects.create(code="AUTO-WEB", name="Automation Web Tenant")
    user = User.objects.create_user(
        email="automation-web@example.com", password="Str0ngPassw0rd!23"
    )
    # "collaborateur" n'est pas dans CORE_MFA_REQUIRED_ROLES — meme choix
    # que `apps.financing.tests.test_views` pour un simple test de rendu
    # d'ecran.
    grant_role(user, "collaborateur")
    return tenant, user


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_flow_list_screen_renders(web_automation) -> None:
    tenant, user = web_automation
    response = _client_for(tenant, user).get("/automation/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_flow_create_screen_renders_and_creates(web_automation) -> None:
    tenant, user = web_automation
    client = _client_for(tenant, user)

    response = client.get("/automation/new/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200

    response = client.post(
        "/automation/new/",
        {"name": "Flux ecran", "trigger_event_type": "workflow.transitioned"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302


def test_flow_create_screen_shows_error_for_unknown_event_type(web_automation) -> None:
    tenant, user = web_automation
    client = _client_for(tenant, user)

    response = client.post(
        "/automation/new/",
        {"name": "Flux invalide", "trigger_event_type": "ceci.n_existe_pas"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    assert b"existe" in response.content or response.context["error"]


def test_flow_builder_screen_renders_and_toggles_active(web_automation) -> None:
    tenant, user = web_automation
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Flux builder", trigger_event_type="workflow.transitioned")
    client = _client_for(tenant, user)

    response = client.get(f"/automation/{flow.id}/builder/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200

    response = client.post(
        f"/automation/{flow.id}/builder/",
        {"action": "toggle_active"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        flow.refresh_from_db()
    assert flow.is_active is True


def test_run_history_screen_renders(web_automation) -> None:
    tenant, user = web_automation
    with use_tenant(tenant.id):
        flow = create_flow(
            tenant, name="Flux historique", trigger_event_type="workflow.transitioned"
        )
    client = _client_for(tenant, user)

    response = client.get(f"/automation/{flow.id}/runs/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_run_detail_screen_renders(web_automation) -> None:
    register_action(
        code="test.views_action",
        module="test",
        label="Action",
        function=lambda tenant_id, params: {"ok": True},
    )
    tenant, user = web_automation
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Flux detail", trigger_event_type="workflow.transitioned")
        add_action_step(flow, action_code="test.views_action")
        from apps.automation.services.engine import run_flow

        run = run_flow(flow, payload={})
    client = _client_for(tenant, user)

    response = client.get(f"/automation/runs/{run.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
