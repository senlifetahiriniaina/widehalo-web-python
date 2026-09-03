"""Écran HTMX du module `analytics` — rendu réel, permissions N2."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.analytics.models import AnMetricDefinition
from apps.analytics.tests.factories import AnMetricDefinitionFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_analytics():
    tenant = Tenant.objects.create(code="AN-WEB", name="Analytics Web Tenant")
    user = User.objects.create_user(email="controleur-an@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "controleur_gestion")
    return tenant, user


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_dashboard_requires_authentication(web_analytics) -> None:
    tenant, _user = web_analytics
    response = Client().get("/analytics/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code in (302, 401, 403)


def test_dashboard_renders_dictionary_tab_for_an_authorized_user(web_analytics) -> None:
    tenant, user = web_analytics
    with use_tenant(tenant.id):
        AnMetricDefinitionFactory(
            tenant=tenant, code="ca.mensuel", libelle="CA mensuel", statut=AnMetricDefinition.STATUT_PUBLIE
        )
    client = _client_for(tenant, user)

    response = client.get("/analytics/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"ca.mensuel" in response.content


def test_dashboard_denies_a_user_without_the_analytics_role(web_analytics) -> None:
    tenant, _user = web_analytics
    other_user = User.objects.create_user(email="collab-an@example.com", password="Str0ngPassw0rd!23")
    grant_role(other_user, "collaborateur")
    client = _client_for(tenant, other_user)

    response = client.get("/analytics/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 403


def test_refresh_now_requires_add_permission(web_analytics) -> None:
    tenant, _user = web_analytics
    viewer = User.objects.create_user(email="viewer-an@example.com", password="Str0ngPassw0rd!23")
    grant_role(viewer, "collaborateur")
    client = _client_for(tenant, viewer)

    response = client.post("/analytics/refresh/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 403
