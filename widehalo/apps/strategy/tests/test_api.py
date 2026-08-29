from __future__ import annotations

import pytest
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
def api_strategy():
    # "commercial" n'est pas dans CORE_MFA_REQUIRED_ROLES (contrairement a
    # "admin"/"direction"/"comptable"/"rh") — meme choix que
    # `apps.crm.tests.test_api` pour eviter le detour MFA dans un test API.
    tenant = Tenant.objects.create(code="STG-API", name="Strategy API Tenant")
    user = User.objects.create_user(email="strategy-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    with use_tenant(tenant.id):
        pass
    return tenant, user


def test_create_and_read_individual_objective_via_api(api_strategy) -> None:
    tenant, user = api_strategy
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/strategy/objectives",
        {
            "title": "Croissance CA 2026",
            "level": "individual",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    objective_id = create_response.json()["id"]

    detail_response = client.get(f"/api/v1/strategy/objectives/{objective_id}", **headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["title"] == "Croissance CA 2026"

    key_result_response = client.post(
        f"/api/v1/strategy/objectives/{objective_id}/key-results",
        {"metric_name": "CA MGA", "target_value": "1000000"},
        content_type="application/json",
        **headers,
    )
    assert key_result_response.status_code == 200
    key_result_id = key_result_response.json()["id"]

    check_in_response = client.post(
        f"/api/v1/strategy/key-results/{key_result_id}/check-ins",
        {"date": "2026-06-01", "value": "500000"},
        content_type="application/json",
        **headers,
    )
    assert check_in_response.status_code == 200
    assert check_in_response.json()["current_value"] == "500000.0000"


def test_collaborateur_cannot_create_company_objective_via_api(api_strategy) -> None:
    tenant, _admin = api_strategy
    collaborateur = User.objects.create_user(
        email="collab-api@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(collaborateur, "collaborateur")
    client = Client()
    token = _access_token(client, collaborateur.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/strategy/objectives",
        {
            "title": "Objectif entreprise interdit",
            "level": "company",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


def test_list_benchmarks_via_api(api_strategy) -> None:
    tenant, user = api_strategy
    with use_tenant(tenant.id):
        from apps.strategy.services.benchmarks import create_sector_benchmark

        create_sector_benchmark(
            tenant,
            sector_code="textile",
            kpi_code="marge_brute_pct",
            kpi_label="Marge brute",
            valid_from="2026-01-01",
        )
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/strategy/benchmarks?sector_code=textile", **headers)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1
