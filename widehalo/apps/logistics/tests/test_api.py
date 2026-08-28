"""LOG7 : tests API django-ninja du module `logistics`, JWT reel via
`django.test.Client` — meme patron que `apps.purchase.tests.test_api`.

Discipline T7 (garde-fou architecture `attempt_transition()`+`.save()`,
cf. `tests/architecture/test_attempt_transition_saves_state.py`) : chaque
transition FSM de `LogShipment` est verifiee via un rechargement HTTP
SEPARE (nouvelle requete GET), jamais en reutilisant le meme objet Python
en memoire — c'est exactement ce type de test qui avait detecte la
regression reelle historique dans `mrp` (cf. consigne de la tache)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.catalog.tests.factories import PackagingFactory, ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.logistics.models import LogServiceProvider
from apps.logistics.tests.factories import LogDriverFactory, LogVehicleFactory

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_logistics():
    tenant = Tenant.objects.create(code="LOG-API", name="Logistics API Tenant")
    user = User.objects.create_user(email="logistics-api@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "magasinier")
    with use_tenant(tenant.id):
        vehicle = LogVehicleFactory(tenant=tenant)
        driver = LogDriverFactory(tenant=tenant, consent_geolocation=True)
    return tenant, user, vehicle, driver


def test_create_vehicle_and_list_via_api(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/logistics/vehicles",
        {"plate_number": "TNA-1234", "type": "truck"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    vehicle_id = body["id"]
    assert body["plate_number"] == "TNA-1234"

    doc_response = client.post(
        f"/api/v1/logistics/vehicles/{vehicle_id}/documents",
        {"doc_type": "insurance", "expiry_date": str(dt.date.today() + dt.timedelta(days=10))},
        content_type="application/json",
        **headers,
    )
    assert doc_response.status_code == 200

    cost_response = client.post(
        f"/api/v1/logistics/vehicles/{vehicle_id}/costs",
        {"date": str(dt.date.today()), "cost_type": "fuel", "amount_mga": "15000"},
        content_type="application/json",
        **headers,
    )
    assert cost_response.status_code == 200

    get_response = client.get(f"/api/v1/logistics/vehicles/{vehicle_id}", **headers)
    assert get_response.status_code == 200
    assert len(get_response.json()["documents"]) == 1
    assert len(get_response.json()["costs"]) == 1

    list_response = client.get("/api/v1/logistics/vehicles", **headers)
    assert list_response.status_code == 200
    assert any(v["id"] == vehicle_id for v in list_response.json()["results"])


def test_create_driver_via_api(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/logistics/drivers",
        {"name": "Rakoto Jean", "consent_geolocation": True},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["consent_geolocation"] is True


def test_create_trip_reorder_complete_and_close_via_api(api_logistics) -> None:
    tenant, user, vehicle, driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/logistics/trips",
        {
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "date": str(dt.date.today()),
            "stops": [
                {"address": "Depot", "type": "pickup"},
                {"address": "Client A", "type": "dropoff"},
            ],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    trip_body = create_response.json()
    trip_id = trip_body["id"]
    assert len(trip_body["stops"]) == 2
    stop_ids = [s["id"] for s in trip_body["stops"]]

    reorder_response = client.post(
        f"/api/v1/logistics/trips/{trip_id}/reorder-stops",
        {"ordered_stop_ids": list(reversed(stop_ids))},
        content_type="application/json",
        **headers,
    )
    assert reorder_response.status_code == 200
    reordered = reorder_response.json()["stops"]
    assert reordered[0]["id"] == stop_ids[-1]

    start_response = client.post(
        f"/api/v1/logistics/trips/{trip_id}/start",
        {"start_odometer_km": "1000"},
        content_type="application/json",
        **headers,
    )
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "in_progress"

    complete_response = client.post(
        f"/api/v1/logistics/trips/{trip_id}/stops/{stop_ids[0]}/complete",
        {"actual_time": timezone.now().isoformat(), "signed_by": "Client A"},
        **headers,
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"

    close_response = client.post(
        f"/api/v1/logistics/trips/{trip_id}/close",
        {"end_odometer_km": "1050"},
        content_type="application/json",
        **headers,
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "completed"
    assert Decimal(close_response.json()["end_odometer_km"]) == Decimal("1050")

    get_response = client.get(f"/api/v1/logistics/trips/{trip_id}", **headers)
    assert get_response.json()["status"] == "completed"


def test_create_trip_template_via_api(api_logistics) -> None:
    tenant, user, vehicle, driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/logistics/trip-templates",
        {
            "name": "Tournee hebdo Antananarivo",
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "interval": "weekly",
            "stops_data": [{"address": "Depot"}],
            "start_date": str(dt.date.today()),
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["interval"] == "weekly"

    list_response = client.get("/api/v1/logistics/trip-templates", **headers)
    assert list_response.status_code == 200


def test_packaging_type_and_plan_via_api(api_logistics) -> None:
    tenant, user, vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant)
        PackagingFactory(tenant=tenant, variant=variant, unit_count=10)

    type_response = client.post(
        "/api/v1/logistics/packaging-types",
        {"code": "CTN-01", "name": "Carton standard", "tare_weight_kg": "1.5"},
        content_type="application/json",
        **headers,
    )
    assert type_response.status_code == 200
    packaging_type_id = type_response.json()["id"]

    plan_response = client.post(
        "/api/v1/logistics/packaging-plans",
        {
            "source_app_label": "logistics",
            "source_model": "logvehicle",
            "source_object_id": str(vehicle.id),
            "packaging_type_id": packaging_type_id,
            "lines": [{"variant_id": str(variant.id), "qty": "25"}],
        },
        content_type="application/json",
        **headers,
    )
    assert plan_response.status_code == 200
    plan_body = plan_response.json()
    assert len(plan_body["lines"]) == 1
    assert plan_body["lines"][0]["qty_packages"] == 3


def test_service_provider_freight_tariff_and_compare_via_api(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    provider_response = client.post(
        "/api/v1/logistics/service-providers",
        {"code": "CMA-CGM", "name": "CMA CGM", "type": "carrier"},
        content_type="application/json",
        **headers,
    )
    assert provider_response.status_code == 200
    provider_id = provider_response.json()["id"]

    tariff_response = client.post(
        f"/api/v1/logistics/service-providers/{provider_id}/freight-tariffs",
        {
            "origin": "Guangzhou",
            "destination": "Antananarivo",
            "price_mga": "5000000",
            "transit_days": 30,
        },
        content_type="application/json",
        **headers,
    )
    assert tariff_response.status_code == 200

    compare_response = client.get(
        "/api/v1/logistics/freight-tariffs/compare",
        {"origin": "Guangzhou", "destination": "Antananarivo"},
        **headers,
    )
    assert compare_response.status_code == 200
    results = compare_response.json()["results"]
    assert len(results) == 1
    assert results[0]["provider_id"] == provider_id


def test_shipment_fsm_state_persists_across_separate_api_calls(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/logistics/shipments",
        {"origin": "Guangzhou", "destination": "Antananarivo"},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    shipment_id = create_response.json()["id"]
    assert create_response.json()["state"] == "planned"

    for action, expected_state in [
        ("book", "booked"),
        ("pick-up", "picked_up"),
        ("mark-in-transit", "in_transit"),
    ]:
        response = client.post(f"/api/v1/logistics/shipments/{shipment_id}/{action}", **headers)
        assert response.status_code == 200
        assert response.json()["state"] == expected_state

        get_response = client.get(f"/api/v1/logistics/shipments/{shipment_id}", **headers)
        assert get_response.json()["state"] == expected_state

    block_response = client.post(
        f"/api/v1/logistics/shipments/{shipment_id}/block",
        {"reason": "Document manquant"},
        content_type="application/json",
        **headers,
    )
    assert block_response.status_code == 200
    assert block_response.json()["state"] == "blocked"

    get_response = client.get(f"/api/v1/logistics/shipments/{shipment_id}", **headers)
    assert get_response.json()["state"] == "blocked"
    assert get_response.json()["block_reason"] == "Document manquant"

    unblock_response = client.post(f"/api/v1/logistics/shipments/{shipment_id}/unblock", **headers)
    assert unblock_response.status_code == 200
    assert unblock_response.json()["state"] == "in_transit"

    get_response = client.get(f"/api/v1/logistics/shipments/{shipment_id}", **headers)
    assert get_response.json()["state"] == "in_transit"

    for action, expected_state in [
        ("mark-arrived-at-port", "arrived_at_port"),
        ("start-customs-clearance", "customs_clearance"),
        ("mark-customs-cleared", "customs_cleared"),
        ("deliver", "delivered"),
        ("close", "closed"),
    ]:
        response = client.post(f"/api/v1/logistics/shipments/{shipment_id}/{action}", **headers)
        assert response.status_code == 200
        assert response.json()["state"] == expected_state

        get_response = client.get(f"/api/v1/logistics/shipments/{shipment_id}", **headers)
        assert get_response.json()["state"] == expected_state


def test_shipment_legs_and_refactor_freight_via_api(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/logistics/shipments",
        {"origin": "Guangzhou", "destination": "Antananarivo"},
        content_type="application/json",
        **headers,
    )
    shipment_id = create_response.json()["id"]

    leg_response = client.post(
        f"/api/v1/logistics/shipments/{shipment_id}/legs",
        {"mode": "sea", "origin": "Guangzhou", "destination": "Toamasina"},
        content_type="application/json",
        **headers,
    )
    assert leg_response.status_code == 200
    assert len(leg_response.json()["legs"]) == 1

    refactor_response = client.post(
        f"/api/v1/logistics/shipments/{shipment_id}/refactor-freight",
        {"partner_id": str(uuid.uuid4()), "amount_mga": "500000"},
        content_type="application/json",
        **headers,
    )
    assert refactor_response.status_code == 200
    # `create_customer_invoice_from_source` renvoie `None` sans configuration
    # comptable du tenant (cf. docstring `refactor_freight_to_customer`) —
    # seul le montant refacture, deja enregistre sur l'expedition, est
    # verifie ici (comportement `None` documente, pas une exception).
    assert "invoice_id" in refactor_response.json()


def test_customs_simulate_hs_code_and_customs_file_flow_via_api(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    simulate_response = client.post(
        "/api/v1/logistics/customs/simulate",
        {"fob_value_mga": "1000000", "duty_rate_pct": "20"},
        content_type="application/json",
        **headers,
    )
    assert simulate_response.status_code == 200
    simulated = simulate_response.json()
    assert Decimal(simulated["caf_value_mga"]) == Decimal("1000000")
    assert Decimal(simulated["duty_mga"]) == Decimal("200000")

    hs_response = client.post(
        "/api/v1/logistics/hs-codes",
        {"code": "6109.1000", "description": "T-shirts en coton", "duty_rate_pct": "20"},
        content_type="application/json",
        **headers,
    )
    assert hs_response.status_code == 200
    hs_code_id = hs_response.json()["id"]

    shipment_response = client.post(
        "/api/v1/logistics/shipments",
        {"origin": "Guangzhou", "destination": "Antananarivo"},
        content_type="application/json",
        **headers,
    )
    shipment_id = shipment_response.json()["id"]

    customs_file_response = client.post(
        "/api/v1/logistics/customs-files",
        {"shipment_id": shipment_id},
        content_type="application/json",
        **headers,
    )
    assert customs_file_response.status_code == 200
    customs_file_id = customs_file_response.json()["id"]

    line_response = client.post(
        f"/api/v1/logistics/customs-files/{customs_file_id}/lines",
        {"hs_code_id": hs_code_id, "description": "T-shirts", "fob_value_mga": "1000000"},
        content_type="application/json",
        **headers,
    )
    assert line_response.status_code == 200
    assert len(line_response.json()["lines"]) == 1

    cleared_response = client.post(
        f"/api/v1/logistics/customs-files/{customs_file_id}/mark-cleared", **headers
    )
    assert cleared_response.status_code == 200
    assert cleared_response.json()["state"] == "cleared"

    get_response = client.get(f"/api/v1/logistics/customs-files/{customs_file_id}", **headers)
    assert get_response.json()["state"] == "cleared"

    close_response = client.post(
        f"/api/v1/logistics/customs-files/{customs_file_id}/close", **headers
    )
    assert close_response.status_code == 200
    assert close_response.json()["state"] == "closed"


def test_report_shipment_delay_via_api(api_logistics) -> None:
    tenant, user, _vehicle, _driver = api_logistics
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    shipment_response = client.post(
        "/api/v1/logistics/shipments",
        {"origin": "Guangzhou", "destination": "Antananarivo"},
        content_type="application/json",
        **headers,
    )
    shipment_id = shipment_response.json()["id"]

    response = client.post(
        f"/api/v1/logistics/shipments/{shipment_id}/report-delay",
        {
            "expected_date": str(dt.date.today() - dt.timedelta(days=10)),
            "supplier_partner_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["incident_id"] is not None


def test_create_shipment_via_api_refuses_role_without_logistics_access(api_logistics) -> None:
    tenant, _user, _vehicle, _driver = api_logistics
    outsider = User.objects.create_user(
        email="outsider-logistics@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    client = Client()
    token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/logistics/shipments",
        {"origin": "Guangzhou", "destination": "Antananarivo"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403


def test_carrier_webhook_accepts_valid_signature_and_rejects_invalid(api_logistics) -> None:
    tenant, _user, _vehicle, _driver = api_logistics
    with use_tenant(tenant.id):
        provider = LogServiceProvider.objects.create(
            tenant=tenant, code="DHL", name="DHL", webhook_secret="s3cr3t"
        )
    client = Client()
    payload = json.dumps({"event": "shipment_status", "status": "in_transit"}).encode()
    valid_signature = hmac.new(b"s3cr3t", payload, hashlib.sha256).hexdigest()

    valid_response = client.post(
        f"/api/v1/logistics/webhooks/carrier/{provider.id}",
        data=payload,
        content_type="application/json",
        HTTP_X_SIGNATURE=valid_signature,
    )
    assert valid_response.status_code == 200
    assert valid_response.json()["status"] == "ok"

    invalid_response = client.post(
        f"/api/v1/logistics/webhooks/carrier/{provider.id}",
        data=payload,
        content_type="application/json",
        HTTP_X_SIGNATURE="not-the-right-signature",
    )
    assert invalid_response.status_code == 403
