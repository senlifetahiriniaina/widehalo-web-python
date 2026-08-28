from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogVehicle, LogVehicleDocument
from apps.logistics.services.vehicles import (
    add_vehicle_document,
    create_driver,
    create_vehicle,
    notify_document_alert,
    record_vehicle_cost,
    upcoming_document_alerts,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="LOG-T", name="Logistics Tenant")


def test_create_vehicle_and_document(tenant) -> None:
    with use_tenant(tenant.id):
        vehicle = create_vehicle(tenant, plate_number="1234 TBA", type=LogVehicle.TYPE_TRUCK)
        assert vehicle.plate_number == "1234 TBA"

        document = add_vehicle_document(
            vehicle,
            doc_type=LogVehicleDocument.TYPE_INSURANCE,
            expiry_date=dt.date.today() + dt.timedelta(days=10),
        )
        assert document.vehicle_id == vehicle.id


def test_duplicate_plate_number_rejected_per_tenant(tenant) -> None:
    with use_tenant(tenant.id):
        create_vehicle(tenant, plate_number="1234 TBA")
        with pytest.raises(ValidationError):
            create_vehicle(tenant, plate_number="1234 TBA")


def test_record_vehicle_cost_updates_odometer(tenant) -> None:
    with use_tenant(tenant.id):
        vehicle = create_vehicle(tenant, plate_number="5678 TBA")
        record_vehicle_cost(
            vehicle,
            date=dt.date.today(),
            cost_type="fuel",
            amount_mga=Decimal("25000"),
            odometer_km=Decimal("1200"),
        )
        vehicle.refresh_from_db()
        assert vehicle.odometer_km == Decimal("1200")


def test_record_vehicle_cost_rejects_non_positive_amount(tenant) -> None:
    with use_tenant(tenant.id):
        vehicle = create_vehicle(tenant, plate_number="9999 TBA")
        with pytest.raises(ValidationError):
            record_vehicle_cost(
                vehicle, date=dt.date.today(), cost_type="fuel", amount_mga=Decimal("0")
            )


def test_create_driver_requires_explicit_consent(tenant) -> None:
    with use_tenant(tenant.id):
        driver = create_driver(tenant, name="Rasoa")
        assert driver.consent_geolocation is False

        driver_with_consent = create_driver(tenant, name="Naina", consent_geolocation=True)
        assert driver_with_consent.consent_geolocation is True


def test_upcoming_document_alerts_within_horizon(tenant) -> None:
    with use_tenant(tenant.id):
        vehicle = create_vehicle(tenant, plate_number="0001 TBA")
        soon = add_vehicle_document(
            vehicle,
            doc_type=LogVehicleDocument.TYPE_TECHNICAL_INSPECTION,
            expiry_date=dt.date.today() + dt.timedelta(days=5),
        )
        far = add_vehicle_document(
            vehicle,
            doc_type=LogVehicleDocument.TYPE_INSURANCE,
            expiry_date=dt.date.today() + dt.timedelta(days=180),
        )

        alerts = upcoming_document_alerts(tenant, within_days=30)

        assert soon in alerts
        assert far not in alerts


def test_notify_document_alert_marks_notified_once(tenant) -> None:
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="fleet@example.com", password="Str0ngPassw0rd!23")
        vehicle = create_vehicle(tenant, plate_number="0002 TBA")
        document = add_vehicle_document(
            vehicle,
            doc_type=LogVehicleDocument.TYPE_INSURANCE,
            expiry_date=dt.date.today() + dt.timedelta(days=3),
        )

        assert document in upcoming_document_alerts(tenant, within_days=30)
        notify_document_alert(document, recipient=user)
        document.refresh_from_db()
        assert document.notified_at is not None
        assert document not in upcoming_document_alerts(tenant, within_days=30)
