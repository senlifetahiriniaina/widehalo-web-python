from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse

from apps.core.models.risk import CATEGORY_PROJECT, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.risk import create_risk_item
from apps.core.tests.utils import use_tenant
from apps.projects.services.projects import create_project

pytestmark = pytest.mark.django_db


@pytest.fixture
def risk_ctx():
    tenant = Tenant.objects.create(code="PRJ-RISK-T1", name="Projects Risk Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet avec risque")
        user = User.objects.create_user(
            email="risk-owner@example.com", password="Str0ngPassw0rd!23"
        )
        yield tenant, project, user


def test_create_risk_item_via_service_links_to_project(risk_ctx) -> None:
    tenant, project, user = risk_ctx
    with use_tenant(tenant.id):
        risk = create_risk_item(
            tenant=tenant,
            category=CATEGORY_PROJECT,
            likelihood=3,
            impact=4,
            owner=user,
            content_object=project,
        )
        assert risk.content_object == project
        assert risk.category == CATEGORY_PROJECT
        assert risk.score == 12


def test_project_risks_screen_lists_only_risks_of_this_project(risk_ctx) -> None:
    tenant, project, user = risk_ctx
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Autre projet")
        create_risk_item(
            tenant=tenant,
            category=CATEGORY_PROJECT,
            likelihood=2,
            impact=2,
            owner=user,
            content_object=project,
        )
        create_risk_item(
            tenant=tenant,
            category=CATEGORY_PROJECT,
            likelihood=5,
            impact=5,
            owner=user,
            content_object=other_project,
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(reverse("projects:risks", args=[project.id]))
    assert response.status_code == 200
    with use_tenant(tenant.id):
        content_type = ContentType.objects.get_for_model(project.__class__)
        risks_in_response = RiskItem.objects.filter(
            content_type=content_type, object_id=str(project.id)
        )
        assert risks_in_response.count() == 1


def test_project_risk_create_screen_signals_a_risk(risk_ctx) -> None:
    tenant, project, user = risk_ctx
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        reverse("projects:risk_create", args=[project.id]),
        {"likelihood": "4", "impact": "5", "mitigation_plan": "Plan de secours"},
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert RiskItem.objects.filter(category=CATEGORY_PROJECT).count() == 1


def test_project_risk_create_rejects_out_of_range_values(risk_ctx) -> None:
    tenant, project, user = risk_ctx
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        reverse("projects:risk_create", args=[project.id]),
        {"likelihood": "9", "impact": "1"},
    )
    assert response.status_code == 200
    assert b"entre 1 et 5" in response.content
