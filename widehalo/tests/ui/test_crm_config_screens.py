from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage, CrmTeam
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def config_screens_setup():
    tenant = Tenant.objects.create(code="UI-CRM-CFG", name="UI CRM Config Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-crm-cfg@example.com", password="Str0ngPassw0rd!23"
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user


def test_config_index_renders(config_screens_setup) -> None:
    client, _tenant, _user = config_screens_setup
    response = client.get("/crm/config/")
    assert response.status_code == 200


def test_config_pipelines_create(config_screens_setup) -> None:
    client, tenant, _user = config_screens_setup
    response = client.post("/crm/config/pipelines/", {"name": "Standard", "is_default": "1"})
    assert response.status_code == 200
    assert b"Standard" in response.content
    with use_tenant(tenant.id):
        assert CrmPipeline.objects.filter(name="Standard").exists()


def test_config_pipeline_detail_add_stage(config_screens_setup) -> None:
    client, tenant, _user = config_screens_setup
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)

    response = client.get(f"/crm/config/pipelines/{pipeline.id}/")
    assert response.status_code == 200

    response = client.post(
        f"/crm/config/pipelines/{pipeline.id}/",
        {"code": "new", "name": "Nouveau", "sequence": "1", "probability": "10"},
    )
    assert response.status_code == 200
    assert b"Nouveau" in response.content
    with use_tenant(tenant.id):
        assert CrmStage.objects.filter(pipeline=pipeline, code="new").exists()


def test_config_teams_create(config_screens_setup) -> None:
    client, tenant, user = config_screens_setup
    response = client.post("/crm/config/teams/", {"name": "Equipe Nord", "leader_id": str(user.id)})
    assert response.status_code == 200
    assert b"Equipe Nord" in response.content
    with use_tenant(tenant.id):
        assert CrmTeam.objects.filter(name="Equipe Nord").exists()


def test_config_lost_reasons_create(config_screens_setup) -> None:
    client, tenant, _user = config_screens_setup
    response = client.post("/crm/config/lost-reasons/", {"name": "Prix trop eleve"})
    assert response.status_code == 200
    assert b"Prix trop" in response.content
    with use_tenant(tenant.id):
        assert CrmLostReason.objects.filter(name="Prix trop eleve").exists()
