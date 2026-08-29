"""Tests des ecrans HTMX qualite (QLT1-2) : liste des gabarits, liste des
inspections, detail — meme idiome que `apps.core.tests.test_risk_screen`."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.factories import QltChecklistTemplateFactory, QltInspectionFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _client_for(user: User, tenant: Tenant) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_template_list_screen_renders_for_authenticated_user() -> None:
    tenant = Tenant.objects.create(code="QLT-SCR-TPL", name="Quality Screen Template Tenant")
    user = User.objects.create_user(
        email="qlt-screen-tpl@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        QltChecklistTemplateFactory(tenant=tenant, name="Controle couture")

    client = _client_for(user, tenant)
    response = client.get("/quality/templates/")

    assert response.status_code == 200
    assert b"Gabarits de controle qualite" in response.content


def test_template_create_screen_renders_form() -> None:
    tenant = Tenant.objects.create(code="QLT-SCR-TPL-NEW", name="Quality Screen Template New")
    user = User.objects.create_user(
        email="qlt-screen-tpl-new@example.com", password="Str0ngPassw0rd!23"
    )
    client = _client_for(user, tenant)

    response = client.get("/quality/templates/new/")

    assert response.status_code == 200
    assert b"Nouveau gabarit de controle" in response.content


def test_template_detail_screen_shows_items() -> None:
    tenant = Tenant.objects.create(code="QLT-SCR-TPL-DET", name="Quality Screen Template Detail")
    user = User.objects.create_user(
        email="qlt-screen-tpl-det@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        template = QltChecklistTemplateFactory(tenant=tenant, name="Controle emballage")

    client = _client_for(user, tenant)
    response = client.get(f"/quality/templates/{template.id}/")

    assert response.status_code == 200
    assert b"Controle emballage" in response.content


def test_inspection_list_screen_renders_for_authenticated_user() -> None:
    tenant = Tenant.objects.create(code="QLT-SCR-INS", name="Quality Screen Inspection Tenant")
    user = User.objects.create_user(
        email="qlt-screen-ins@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        QltInspectionFactory(tenant=tenant)

    client = _client_for(user, tenant)
    response = client.get("/quality/inspections/")

    assert response.status_code == 200
    assert b"Inspections qualite" in response.content


def test_inspection_detail_screen_shows_result() -> None:
    tenant = Tenant.objects.create(code="QLT-SCR-INS-DET", name="Quality Screen Inspection Detail")
    user = User.objects.create_user(
        email="qlt-screen-ins-det@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        inspection = QltInspectionFactory(tenant=tenant, passed=False)

    client = _client_for(user, tenant)
    response = client.get(f"/quality/inspections/{inspection.id}/")

    assert response.status_code == 200
    assert b"Non conforme" in response.content
