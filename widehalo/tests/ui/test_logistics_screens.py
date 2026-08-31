from __future__ import annotations

import datetime as dt

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogHsCode, LogServiceProvider
from apps.logistics.services.shipments import create_shipment
from apps.logistics.services.trips import create_trip
from apps.logistics.tests.factories import LogDriverFactory, LogVehicleFactory
from django.contrib.auth.models import Group
from django.test import Client
from django_otp.oath import totp

pytestmark = pytest.mark.django_db


@pytest.fixture
def logistics_screens_setup():
    tenant = Tenant.objects.create(code="UI-LOG", name="UI Logistics Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-log@example.com", password="Str0ngPassw0rd!23")
        vehicle = LogVehicleFactory(tenant=tenant)
        driver = LogDriverFactory(tenant=tenant, consent_geolocation=True)
        trip = create_trip(
            tenant,
            vehicle=vehicle,
            driver=driver,
            date=dt.date.today(),
            stops=[{"address": "Depot"}],
        )
        shipment = create_shipment(tenant, origin="Guangzhou", destination="Antananarivo")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, vehicle, driver, trip, shipment


def test_vehicle_list_screen_renders(logistics_screens_setup) -> None:
    client, *_ = logistics_screens_setup
    response = client.get("/logistics/")
    assert response.status_code == 200


def test_vehicle_create_screen(logistics_screens_setup) -> None:
    client, *_ = logistics_screens_setup
    response = client.post("/logistics/vehicles/new/", {"plate_number": "TNA-9999", "type": "van"})
    assert response.status_code == 302


def test_vehicle_detail_add_document_and_cost(logistics_screens_setup) -> None:
    client, tenant, _user, vehicle, *_ = logistics_screens_setup

    response = client.post(
        f"/logistics/vehicles/{vehicle.id}/",
        {"action": "add_document", "doc_type": "insurance", "alert_days_before": "30"},
    )
    assert response.status_code == 302

    response = client.post(
        f"/logistics/vehicles/{vehicle.id}/",
        {
            "action": "add_cost",
            "date": str(dt.date.today()),
            "cost_type": "fuel",
            "amount_mga": "20000",
        },
    )
    assert response.status_code == 302

    detail = client.get(f"/logistics/vehicles/{vehicle.id}/")
    assert detail.status_code == 200
    assert b"20000" in detail.content


def test_driver_list_screen_create(logistics_screens_setup) -> None:
    client, *_ = logistics_screens_setup
    response = client.get("/logistics/drivers/")
    assert response.status_code == 200

    response = client.post("/logistics/drivers/", {"name": "Rakoto Jean"})
    assert response.status_code == 302


def test_trip_list_and_create_screens(logistics_screens_setup) -> None:
    client, _tenant, _user, vehicle, driver, *_ = logistics_screens_setup

    response = client.get("/logistics/trips/")
    assert response.status_code == 200

    response = client.post(
        "/logistics/trips/new/",
        {
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "date": str(dt.date.today()),
            "stop_addresses": "Depot\nClient A",
        },
    )
    assert response.status_code == 302


def test_trip_detail_start_and_close_flow(logistics_screens_setup) -> None:
    client, tenant, _user, _vehicle, _driver, trip, _shipment = logistics_screens_setup

    response = client.post(
        f"/logistics/trips/{trip.id}/", {"action": "start", "start_odometer_km": "100"}
    )
    assert response.status_code == 302

    response = client.post(
        f"/logistics/trips/{trip.id}/", {"action": "close", "end_odometer_km": "150"}
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        trip.refresh_from_db()
        assert trip.status == "completed"


def test_trip_template_list_screen_create(logistics_screens_setup) -> None:
    client, _tenant, _user, vehicle, driver, *_ = logistics_screens_setup

    response = client.get("/logistics/trip-templates/")
    assert response.status_code == 200

    response = client.post(
        "/logistics/trip-templates/",
        {
            "name": "Tournee hebdo",
            "vehicle_id": str(vehicle.id),
            "driver_id": str(driver.id),
            "interval": "weekly",
            "start_date": str(dt.date.today()),
            "stop_addresses": "Depot",
        },
    )
    assert response.status_code == 302


def test_shipment_list_and_create_screens(logistics_screens_setup) -> None:
    client, *_ = logistics_screens_setup

    response = client.get("/logistics/shipments/")
    assert response.status_code == 200
    response = client.get("/logistics/shipments/?state=planned")
    assert response.status_code == 200

    response = client.post(
        "/logistics/shipments/new/", {"origin": "Guangzhou", "destination": "Antananarivo"}
    )
    assert response.status_code == 302


def test_shipment_detail_fsm_bandeau_progresses_via_redirects(logistics_screens_setup) -> None:
    """Chaque action du bandeau de workflow repond par une redirection
    (302), jamais un re-rendu de page complete depuis le formulaire
    d'action — meme convention que `tests/ui/test_purchase_screens.py`."""
    client, tenant, _user, _vehicle, _driver, _trip, shipment = logistics_screens_setup

    for action in ("book", "pick_up", "mark_in_transit"):
        response = client.post(f"/logistics/shipments/{shipment.id}/", {"action": action})
        assert response.status_code == 302

    detail = client.get(f"/logistics/shipments/{shipment.id}/")
    assert b"En transit" in detail.content

    with use_tenant(tenant.id):
        shipment.refresh_from_db()
        assert shipment.state == "in_transit"


def test_shipment_detail_block_requires_reason_and_unblocks(logistics_screens_setup) -> None:
    client, tenant, _user, _vehicle, _driver, _trip, shipment = logistics_screens_setup
    client.post(f"/logistics/shipments/{shipment.id}/", {"action": "book"})
    client.post(f"/logistics/shipments/{shipment.id}/", {"action": "pick_up"})
    client.post(f"/logistics/shipments/{shipment.id}/", {"action": "mark_in_transit"})

    response = client.post(
        f"/logistics/shipments/{shipment.id}/", {"action": "block", "reason": "Document manquant"}
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        shipment.refresh_from_db()
        assert shipment.state == "blocked"

    response = client.post(f"/logistics/shipments/{shipment.id}/", {"action": "unblock"})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        shipment.refresh_from_db()
        assert shipment.state == "in_transit"


def test_shipment_detail_open_customs_file_redirects_to_customs_screen(
    logistics_screens_setup,
) -> None:
    client, tenant, _user, _vehicle, _driver, _trip, shipment = logistics_screens_setup

    response = client.post(f"/logistics/shipments/{shipment.id}/", {"action": "open_customs_file"})
    assert response.status_code == 302
    assert response.url.startswith("/logistics/customs-files/")

    with use_tenant(tenant.id):
        assert shipment.customs_files.count() == 1


def test_customs_file_detail_add_line_mark_cleared_and_close(logistics_screens_setup) -> None:
    client, tenant, _user, _vehicle, _driver, _trip, shipment = logistics_screens_setup
    with use_tenant(tenant.id):
        hs_code = LogHsCode.objects.create(
            tenant=tenant, code="6109.1000", description="T-shirts", duty_rate_pct="20"
        )

    open_response = client.post(
        f"/logistics/shipments/{shipment.id}/", {"action": "open_customs_file"}
    )
    customs_file_url = open_response.url

    response = client.post(
        customs_file_url,
        {
            "action": "add_line",
            "hs_code_id": str(hs_code.id),
            "description": "T-shirts en coton",
            "fob_value_mga": "1000000",
        },
    )
    assert response.status_code == 302

    response = client.post(customs_file_url, {"action": "mark_cleared"})
    assert response.status_code == 302

    detail = client.get(customs_file_url)
    assert b"Dedouane" in detail.content or b"cleared" in detail.content.lower()

    response = client.post(customs_file_url, {"action": "close"})
    assert response.status_code == 302


def test_config_screens_render_and_create(logistics_screens_setup) -> None:
    client, tenant, *_ = logistics_screens_setup

    response = client.get("/logistics/config/")
    assert response.status_code == 200

    response = client.get("/logistics/config/packaging-types/")
    assert response.status_code == 200
    response = client.post(
        "/logistics/config/packaging-types/",
        {"code": "CTN-UI", "name": "Carton UI", "tare_weight_kg": "1"},
    )
    assert response.status_code == 302

    response = client.get("/logistics/config/service-providers/")
    assert response.status_code == 200
    response = client.post(
        "/logistics/config/service-providers/",
        {"action": "create_provider", "code": "PRV-UI", "name": "Transporteur UI"},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        provider = LogServiceProvider.objects.get(code="PRV-UI")
    response = client.post(
        "/logistics/config/service-providers/",
        {
            "action": "create_tariff",
            "provider_id": str(provider.id),
            "origin": "Guangzhou",
            "destination": "Antananarivo",
            "price_mga": "1000000",
            "transit_days": "20",
        },
    )
    assert response.status_code == 302

    response = client.get("/logistics/config/hs-codes/")
    assert response.status_code == 200
    response = client.post(
        "/logistics/config/hs-codes/",
        {"code": "6109.2000", "description": "T-shirts synthetiques", "duty_rate_pct": "20"},
    )
    assert response.status_code == 302


def test_reports_screen_and_downloads(logistics_screens_setup) -> None:
    client, *_ = logistics_screens_setup

    response = client.get("/logistics/reports/")
    assert response.status_code == 200

    response = client.get("/logistics/reports/vehicle-costs/")
    assert response.status_code == 200
    response = client.get("/logistics/reports/shipments/")
    assert response.status_code == 200
    response = client.get("/logistics/reports/customs/")
    assert response.status_code == 200


def test_settings_hub_links_to_logistics_config(logistics_screens_setup) -> None:
    """`/settings/` est desormais restreint admin/direction/superutilisateur
    (chantier menu compte utilisateur / section Administration) — un
    utilisateur admin dedie a ce seul test (jamais ajoute au fixture
    partage `logistics_screens_setup`, qui redeviendrait alors soumis a
    MFA obligatoire pour TOUS les autres tests de ce fichier)."""
    _, tenant, *_ = logistics_screens_setup

    admin_user = User.objects.create_user(
        email="ui-log-admin@example.com", password="Str0ngPassw0rd!23"
    )
    admin_group, _ = Group.objects.get_or_create(name="admin")
    admin_user.groups.add(admin_group)
    admin_client = Client()
    response = admin_client.post(
        "/login/", {"email": admin_user.email, "password": "Str0ngPassw0rd!23"}
    )
    assert response.status_code == 302, response.content
    session = admin_client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    admin_client.get("/mfa/")
    device = mfa_service.enroll_device(admin_user)
    token = str(totp(device.bin_key)).zfill(6)
    response = admin_client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content

    response = admin_client.get("/settings/")
    assert response.status_code == 200
    assert b"/logistics/config/" in response.content
