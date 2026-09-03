"""Écrans HTMX du module `simulation` — rendu réel, permissions N2,
scope N3 (SIM-9)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.simulation.models import SimScenario
from apps.simulation.services.baseline import deserialize_baseline_data
from apps.simulation.services.engine import compute_indicators
from apps.simulation.tests.factories import SimBaselineFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_simulation():
    tenant = Tenant.objects.create(code="SIM-WEB", name="Simulation Web Tenant")
    user = User.objects.create_user(email="controleur@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "controleur_gestion")
    return tenant, user


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_library_requires_authentication(web_simulation) -> None:
    tenant, _user = web_simulation
    response = Client().get("/simulation/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code in (302, 401, 403)


def test_library_renders_for_an_authorized_user(web_simulation) -> None:
    tenant, user = web_simulation
    client = _client_for(tenant, user)

    response = client.get("/simulation/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200


def test_workbench_shows_construction_prompt_without_a_baseline(web_simulation) -> None:
    tenant, user = web_simulation
    client = _client_for(tenant, user)

    response = client.get("/simulation/workbench/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert "Construire le socle de simulation".encode() in response.content


def test_workbench_renders_the_engine_when_a_baseline_exists(web_simulation) -> None:
    tenant, user = web_simulation
    with use_tenant(tenant.id):
        SimBaselineFactory(tenant=tenant)
    client = _client_for(tenant, user)

    response = client.get("/simulation/workbench/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"simWorkbench(" in response.content
    assert b"simulation_engine.js" in response.content


def test_workbench_post_creates_a_scenario_with_a_matching_client_computation(web_simulation) -> None:
    tenant, user = web_simulation
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        levers = {"prix_vente_pct": "10"}
        indicators = compute_indicators(deserialize_baseline_data(baseline), {"prix_vente_pct": Decimal(10)})
        payload = {
            "name": "Scénario web",
            "description": "",
            "is_shared": False,
            "levers": levers,
            "client_computed_indicators": _to_float_tree(indicators),
        }
    client = _client_for(tenant, user)

    response = client.post(
        "/simulation/workbench/",
        {"baseline_id": str(baseline.id), "scenario_json": json.dumps(payload)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )

    assert response.status_code == 302
    with use_tenant(tenant.id):
        scenario = SimScenario.objects.get(name="Scénario web")
        assert scenario.computed_indicators["ca"] == "110000000"


def test_workbench_post_rejects_a_diverging_client_computation(web_simulation) -> None:
    tenant, user = web_simulation
    with use_tenant(tenant.id):
        baseline = SimBaselineFactory(tenant=tenant)
        payload = {
            "name": "Divergent",
            "levers": {"prix_vente_pct": "10"},
            "client_computed_indicators": {"ca": 1},
        }
    client = _client_for(tenant, user)

    response = client.post(
        "/simulation/workbench/",
        {"baseline_id": str(baseline.id), "scenario_json": json.dumps(payload)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )

    assert response.status_code == 302
    assert "error=" in response["Location"]
    with use_tenant(tenant.id):
        assert not SimScenario.objects.filter(name="Divergent").exists()


def test_workbench_denies_a_role_without_simulation_access() -> None:
    tenant = Tenant.objects.create(code="SIM-DENY", name="Simulation Deny Tenant")
    user = User.objects.create_user(email="commercial@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")
    client = _client_for(tenant, user)

    response = client.get("/simulation/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 403


def _to_float_tree(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _to_float_tree(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_float_tree(val) for val in value]
    return value
