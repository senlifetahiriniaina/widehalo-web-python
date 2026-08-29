from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import create_objective

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_strategy():
    tenant = Tenant.objects.create(code="STG-WEB", name="Strategy Web Tenant")
    user = User.objects.create_user(email="strategy-web@example.com", password="Str0ngPassw0rd!23")
    # "collaborateur" n'est pas dans CORE_MFA_REQUIRED_ROLES — meme choix
    # que `apps.presence.tests.test_views` pour un simple test d'ecran.
    grant_role(user, "collaborateur")
    return tenant, user


def test_objective_list_screen_renders(web_strategy) -> None:
    tenant, user = web_strategy
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/strategy/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_objective_detail_screen_renders(web_strategy) -> None:
    tenant, user = web_strategy
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif ecran",
            level=StgObjective.LEVEL_COMPANY,
            period_start="2026-01-01",
            period_end="2026-12-31",
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/strategy/{objective.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert "Objectif ecran" in response.content.decode()


def test_capacity_outlook_screen_renders(web_strategy) -> None:
    """CAP1-2 (cf. plan) : ecran HTMX minimal du tableau capacite-vs-charge."""
    tenant, user = web_strategy
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/strategy/capacity/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert "Capacite" in response.content.decode()


def test_capacity_outlook_screen_accepts_custom_horizon(web_strategy) -> None:
    tenant, user = web_strategy
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(
        "/strategy/capacity/", {"horizon_days": "14"}, HTTP_X_TENANT_ID=str(tenant.id)
    )

    assert response.status_code == 200
