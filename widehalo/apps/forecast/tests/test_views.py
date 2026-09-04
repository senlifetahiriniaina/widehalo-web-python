"""Écrans HTMX du module `forecast` — rendu réel, permissions N2."""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.forecast.tests.factories import ForSeriesForecastFactory
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_forecast():
    tenant = Tenant.objects.create(code="FOR-WEB", name="Forecast Web Tenant")
    # `controleur_gestion` : hors `CORE_MFA_REQUIRED_ROLES`, memes droits
    # complets sur `forecast` (cf. rbac_policy.py) — meme discipline que
    # apps.bi.tests.test_views/apps.simulation.tests.test_views.
    user = User.objects.create_user(
        email="controleur-for@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "controleur_gestion")
    return tenant, user


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_dashboard_requires_authentication(web_forecast) -> None:
    tenant, _user = web_forecast
    response = Client().get("/forecast/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code in (302, 401, 403)


def test_dashboard_denies_a_user_without_the_forecast_role(web_forecast) -> None:
    tenant, _user = web_forecast
    other = User.objects.create_user(email="collab-for@example.com", password="Str0ngPassw0rd!23")
    grant_role(other, "collaborateur")
    client = _client_for(tenant, other)

    response = client.get("/forecast/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 403


def test_dashboard_renders_consolidated_tab(web_forecast) -> None:
    tenant, user = web_forecast
    with use_tenant(tenant.id):
        ForSeriesForecastFactory(tenant=tenant, dimension_value="pos")
    client = _client_for(tenant, user)

    response = client.get("/forecast/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"pos" in response.content


def test_workbench_renders_history_and_forecasts(web_forecast) -> None:
    tenant, user = web_forecast
    with use_tenant(tenant.id):
        ForSeriesForecastFactory(
            tenant=tenant, dimension_type="canal", dimension_value="vente_directe"
        )
    client = _client_for(tenant, user)

    response = client.get(
        "/forecast/workbench/?dimension_type=canal&dimension_value=vente_directe",
        HTTP_X_TENANT_ID=str(tenant.id),
    )

    assert response.status_code == 200
