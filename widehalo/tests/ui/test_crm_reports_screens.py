from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage
from apps.crm.services.leads import create_lead_quick
from apps.crm.services.pipeline import move_lead_to_stage
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def crm_reports_setup():
    tenant = Tenant.objects.create(code="UI-CRM-RPT", name="UI CRM Reports Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-crm-rpt@example.com", password="Str0ngPassw0rd!23"
        )
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)
        stage_new = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="new", name="Nouveau", sequence=1
        )
        stage_won = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="won",
            name="Gagne",
            sequence=2,
            is_won=True,
        )
        stage_lost = CrmStage.objects.create(
            tenant=tenant,
            pipeline=pipeline,
            code="lost",
            name="Perdu",
            sequence=3,
            is_lost=True,
        )
        lost_reason = CrmLostReason.objects.create(tenant=tenant, name="Prix trop eleve")

        lead_open = create_lead_quick(
            tenant=tenant, name="Uniformes GN Antsirabe", expected_revenue_mga=1000000
        )
        assert lead_open.stage_id == stage_new.id

        lead_won = create_lead_quick(
            tenant=tenant, name="EPI TotalEnergies", expected_revenue_mga=2000000
        )
        move_lead_to_stage(lead_won, stage_won)

        lead_lost = create_lead_quick(
            tenant=tenant, name="Combinaisons Sen Glory", expected_revenue_mga=500000
        )
        move_lead_to_stage(lead_lost, stage_lost, lost_reason=lost_reason, comment="Trop cher")

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, pipeline


def test_reports_index_screen_renders(crm_reports_setup) -> None:
    client, _tenant, _pipeline = crm_reports_setup
    response = client.get("/crm/reports/")
    assert response.status_code == 200


def test_pipeline_report_download_json(crm_reports_setup) -> None:
    client, _tenant, pipeline = crm_reports_setup
    response = client.get("/crm/reports/pipeline/", {"pipeline_id": str(pipeline.id)})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response["Content-Disposition"].startswith("attachment;")
    assert b"new" in response.content


def test_conversion_report_download_json(crm_reports_setup) -> None:
    client, _tenant, pipeline = crm_reports_setup
    response = client.get("/crm/reports/conversion/", {"pipeline_id": str(pipeline.id)})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b'"won": 1' in response.content
    assert b'"lost": 1' in response.content


def test_activities_report_download_json(crm_reports_setup) -> None:
    client, _tenant, _pipeline = crm_reports_setup
    response = client.get("/crm/reports/activities/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_lost_report_download_json(crm_reports_setup) -> None:
    client, _tenant, _pipeline = crm_reports_setup
    response = client.get("/crm/reports/lost/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"Prix trop eleve" in response.content
