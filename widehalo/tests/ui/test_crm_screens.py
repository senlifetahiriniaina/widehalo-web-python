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


def test_lead_detail_add_line_shows_in_table(crm_screens_setup) -> None:
    client, _tenant, lead = crm_screens_setup

    response = client.post(
        f"/crm/{lead.id}/",
        {
            "action": "add_line",
            "description": "Uniforme brode",
            "qty": "3",
            "unit_price": "15000",
            "discount_pct": "5",
        },
    )
    assert response.status_code == 302

    detail = client.get(f"/crm/{lead.id}/")
    assert detail.status_code == 200
    assert b"Uniforme brode" in detail.content


def test_lead_detail_line_above_discount_threshold_requires_approval(crm_screens_setup) -> None:
    from django.contrib.auth.models import Group

    client, tenant, lead = crm_screens_setup
    with use_tenant(tenant.id):
        group, _ = Group.objects.get_or_create(name="commercial")
        user = User.objects.get(email="ui-crm@example.com")
        user.groups.add(group)

    response = client.post(
        f"/crm/{lead.id}/",
        {
            "action": "add_line",
            "description": "Combinaison sur mesure",
            "qty": "1",
            "unit_price": "50000",
            "discount_pct": "40",
        },
    )
    assert response.status_code == 200
    assert b"validation" in response.content.lower() or b"approbat" in response.content.lower()

    detail = client.get(f"/crm/{lead.id}/")
    assert b"Combinaison sur mesure" in detail.content
