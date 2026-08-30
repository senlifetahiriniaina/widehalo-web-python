from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

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
def api_ai():
    # `ai` (budget de tokens) est scope explicitement a `admin`/`direction`
    # — tous deux dans `CORE_MFA_REQUIRED_ROLES`, ce qui bloquerait la
    # connexion JWT de ce test tant qu'un device TOTP n'est pas enrole
    # (meme constat/meme contournement que `apps.financing.tests.
    # test_api`) : groupe ad hoc portant les permissions `ai` reellement
    # exercees, plutot que `grant_role("admin")`.
    tenant = Tenant.objects.create(code="AI-API", name="AI API Tenant")
    user = User.objects.create_user(email="ai-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="ai-api-test")
    group.permissions.set(
        Permission.objects.filter(
            content_type__app_label="ai",
            codename__in=[
                "view_aiusagelimit",
                "add_aiusagelimit",
                "change_aiusagelimit",
                "view_airequest",
            ],
        )
    )
    user.groups.add(group)
    return tenant, user


def test_get_and_update_usage_budget_via_api(api_ai) -> None:
    tenant, user = api_ai
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    get_response = client.get("/api/v1/ai/usage/budget", **headers)
    assert get_response.status_code == 200
    assert get_response.json()["monthly_token_budget"] > 0

    update_response = client.post(
        "/api/v1/ai/usage/budget",
        {"monthly_token_budget": 5000, "alert_threshold_pct": 90, "hard_stop": True},
        content_type="application/json",
        **headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["monthly_token_budget"] == 5000

    get_again = client.get("/api/v1/ai/usage/budget", **headers)
    assert get_again.json()["monthly_token_budget"] == 5000


def test_list_usage_requests_via_api_is_tenant_scoped(api_ai) -> None:
    tenant, user = api_ai
    from apps.ai.models import AiRequest
    from apps.ai.services.usage_budget import record_request
    from apps.core.services.ai_assistant import StubAIProvider

    with use_tenant(tenant.id):
        record_request(
            tenant,
            feature=AiRequest.FEATURE_ASSIST,
            prompt_tokens_estimate=10,
            completion_tokens_estimate=5,
            provider=StubAIProvider(),
        )

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))
    response = client.get("/api/v1/ai/usage", **headers)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_rbac_deny_for_role_without_ai_access() -> None:
    tenant = Tenant.objects.create(code="AI-DENY", name="AI Deny Tenant")
    user = User.objects.create_user(email="ai-deny@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))
    response = client.get("/api/v1/ai/usage/budget", **headers)
    assert response.status_code == 403
