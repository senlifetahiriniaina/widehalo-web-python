from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.crm.services.leads import create_lead_quick
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def crm_screens_setup():
    tenant = Tenant.objects.create(code="UI-CRM", name="UI CRM Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-crm@example.com", password="Str0ngPassw0rd!23")
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)
        stage_new = CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="new", name="Nouveau", sequence=1
        )
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="qualified", name="Qualifie", sequence=2
        )
        lead = create_lead_quick(tenant=tenant, name="Opportunite textile")
        assert lead.stage_id == stage_new.id
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, lead


def test_lead_create_screen(crm_screens_setup) -> None:
    client, _tenant, _lead = crm_screens_setup
    response = client.post("/crm/new/", {"name": "Nouvelle opportunite"})
    assert response.status_code == 302


def test_lead_detail_move_stage(crm_screens_setup) -> None:
    client, tenant, lead = crm_screens_setup
    with use_tenant(tenant.id):
        target_stage = CrmStage.objects.get(code="qualified")

    response = client.post(
        f"/crm/{lead.id}/",
        {"action": "move_stage", "stage_id": str(target_stage.id)},
    )
    assert response.status_code == 302

    detail = client.get(f"/crm/{lead.id}/")
    assert b"Qualifie" in detail.content


def test_lead_list_screen_renders(crm_screens_setup) -> None:
    client, _tenant, _lead = crm_screens_setup
    response = client.get("/crm/")
    assert response.status_code == 200
