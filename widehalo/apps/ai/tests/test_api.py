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
                "view_aianomaly",
                "add_aianomaly",
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


def test_assist_endpoint_is_reachable_by_any_authenticated_role_no_permission_needed() -> None:
    """AI2 : cadrage explicite du plan — `POST /ai/assist` et
    `GET /ai/assist/modules` sont accessibles a n'importe quel role, sans
    `require_permission`, meme un role sans aucune permission `ai.*`
    (contrairement aux endpoints de budget ci-dessus)."""
    tenant = Tenant.objects.create(code="AI-ASSIST-API", name="AI Assist API Tenant")
    user = User.objects.create_user(email="assist-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    modules_response = client.get("/api/v1/ai/assist/modules", **headers)
    assert modules_response.status_code == 200
    assert isinstance(modules_response.json()["results"], list)

    assist_response = client.post(
        "/api/v1/ai/assist",
        {"module": "sales", "action": "consulter"},
        content_type="application/json",
        **headers,
    )
    assert assist_response.status_code == 200
    body = assist_response.json()
    assert body["module"] == "sales"
    assert body["guidance"]
    assert body["is_ai_generated"] is False


def test_assist_endpoint_never_errors_for_an_unregistered_module() -> None:
    tenant = Tenant.objects.create(code="AI-ASSIST-404", name="AI Assist Unregistered Tenant")
    user = User.objects.create_user(email="assist-404@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/ai/assist",
        {"module": "module_totalement_inconnu", "action": "consulter"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["is_ai_generated"] is False


@pytest.fixture(autouse=True)
def _isolated_anomaly_registry(monkeypatch):
    """Meme raisonnement que `apps.ai.tests.test_anomaly_detection` : le
    registre `core.services.anomaly_registry._REGISTRY` est un dict global
    au processus, jamais nettoye entre tests — isole ici pour que
    `POST /ai/anomalies/detect` ne remonte QUE les checks enregistres par
    CE test (les vrais checks metier accounting/stocks/projects/sales
    resteraient inoffensifs sur un tenant frais sans donnees, mais
    l'isolation reste la garantie la plus explicite)."""
    import apps.core.services.anomaly_registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", {})


def test_detect_and_list_anomalies_via_api(api_ai) -> None:
    from apps.core.services.anomaly_registry import (
        SEVERITY_HIGH,
        AnomalyCandidate,
        register_anomaly_check,
    )

    tenant, user = api_ai

    def _check(tenant_id: str) -> list:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_HIGH,
                description="Anomalie de test API.",
            )
        ]

    register_anomaly_check("test.api_detect", module="test", label="API", function=_check)

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    detect_response = client.post("/api/v1/ai/anomalies/detect", **headers)
    assert detect_response.status_code == 200
    detected = detect_response.json()["results"]
    assert len(detected) == 1
    assert detected[0]["check_code"] == "test.api_detect"
    assert detected[0]["severity"] == SEVERITY_HIGH

    list_response = client.get("/api/v1/ai/anomalies", **headers)
    assert list_response.status_code == 200
    listed = list_response.json()["results"]
    assert len(listed) == 1
    assert listed[0]["id"] == detected[0]["id"]

    filtered_response = client.get("/api/v1/ai/anomalies", {"severity": "faible"}, **headers)
    assert filtered_response.json()["results"] == []


def test_rbac_deny_anomaly_endpoints_for_role_without_ai_access() -> None:
    tenant = Tenant.objects.create(code="AI-ANOM-DENY", name="AI Anomaly Deny Tenant")
    user = User.objects.create_user(email="ai-anom-deny@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "resp_commercial")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    assert client.post("/api/v1/ai/anomalies/detect", **headers).status_code == 403
    assert client.get("/api/v1/ai/anomalies", **headers).status_code == 403
