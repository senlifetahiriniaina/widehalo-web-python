from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.feasibility.services.simulation import create_study

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_feasibility():
    tenant = Tenant.objects.create(code="FEA-WEB", name="Feasibility Web Tenant")
    user = User.objects.create_user(
        email="feasibility-web@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "resp_commercial")
    return tenant, user


def test_study_list_screen_renders(web_feasibility) -> None:
    tenant, user = web_feasibility
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/feasibility/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_study_detail_screen_renders_and_add_line(web_feasibility) -> None:
    tenant, user = web_feasibility
    with use_tenant(tenant.id):
        study = create_study(tenant, name="Etude ecran", owner=user, created_by=user)

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    detail_response = client.get(f"/feasibility/{study.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert detail_response.status_code == 200

    add_line_response = client.post(
        f"/feasibility/{study.id}/",
        {
            "action": "add_line",
            "hypothetical_name": "Produit test ecran",
            "assumed_qty": "5",
            "assumed_unit_price_mga": "10000",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert add_line_response.status_code == 200
    with use_tenant(tenant.id):
        assert study.lines.count() == 1


def test_study_create_screen(web_feasibility) -> None:
    tenant, user = web_feasibility
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    create_response = client.post(
        "/feasibility/new/",
        {"name": "Nouvelle etude ecran", "sector_code": "textile"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert create_response.status_code == 302
