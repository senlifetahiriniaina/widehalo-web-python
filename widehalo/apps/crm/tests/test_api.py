from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


@pytest.fixture
def api_crm():
    tenant = Tenant.objects.create(code="CRM-API", name="CRM API Tenant")
    user = User.objects.create_user(email="crm-api@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        stage = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )
        won_stage = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="gagne", name="Gagne", sequence=2, is_won=True
        )
    return tenant, user, pipeline, stage, won_stage


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_create_and_move_lead_via_api(api_crm) -> None:
    tenant, user, pipeline, _stage, won_stage = api_crm
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/crm/leads",
        {"name": "Opportunite API", "pipeline_id": str(pipeline.id)},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    lead_id = body["id"]
    assert body["stage"] == "nouveau"
    assert body["reference"].startswith("LEAD-")

    move_response = client.post(
        f"/api/v1/crm/leads/{lead_id}/move-stage",
        {"stage_id": str(won_stage.id)},
        content_type="application/json",
        **headers,
    )
    assert move_response.status_code == 200
    assert move_response.json()["stage"] == "gagne"


def test_list_leads_via_api(api_crm) -> None:
    tenant, user, pipeline, _stage, _won = api_crm
    # RG-CRM-5 : create_lead_endpoint assigne l'appelant comme vendeur, donc
    # le scoping par defaut ("commercial" implicite : salesperson=user) le
    # rend deja visible sans avoir besoin d'un role/groupe supplementaire.
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    client.post(
        "/api/v1/crm/leads",
        {"name": "Opportunite Listee", "pipeline_id": str(pipeline.id)},
        content_type="application/json",
        **headers,
    )
    response = client.get("/api/v1/crm/leads", **headers)
    assert response.status_code == 200
    names = {lead["reference"] for lead in response.json()["results"]}
    assert len(names) == 1


def test_lead_activity_roundtrip_via_api(api_crm) -> None:
    tenant, user, pipeline, _stage, _won = api_crm
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/crm/leads",
        {"name": "Opportunite Activite", "pipeline_id": str(pipeline.id)},
        content_type="application/json",
        **headers,
    )
    lead_id = create_response.json()["id"]

    activity_response = client.post(
        f"/api/v1/crm/leads/{lead_id}/activities",
        {"activity_type": "call", "subject": "Premier contact"},
        content_type="application/json",
        **headers,
    )
    assert activity_response.status_code == 200

    timeline_response = client.get(f"/api/v1/crm/leads/{lead_id}/activities", **headers)
    assert timeline_response.status_code == 200
    assert len(timeline_response.json()["results"]) == 1


def test_pipeline_report_via_api(api_crm) -> None:
    tenant, user, pipeline, _stage, _won = api_crm
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    client.post(
        "/api/v1/crm/leads",
        {"name": "Opportunite Rapport", "pipeline_id": str(pipeline.id)},
        content_type="application/json",
        **headers,
    )
    response = client.get(f"/api/v1/crm/reports/pipeline?pipeline_id={pipeline.id}", **headers)
    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["lead_count"] == 1
