from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogTripStop, LogTripTemplate
from apps.logistics.services.trips import (
    close_trip,
    create_trip,
    create_trip_template,
    generate_due_trip,
    get_stop_location,
    record_stop_completion,
    reorder_stops,
    start_trip,
    suggest_stop_order,
)
from apps.logistics.services.vehicles import create_driver, create_vehicle

pytestmark = pytest.mark.django_db


@pytest.fixture
def trip_setup():
    tenant = Tenant.objects.create(code="LOG-TRIP-T", name="Logistics Trip Tenant")
    with use_tenant(tenant.id):
        vehicle = create_vehicle(tenant, plate_number="1111 TBA")
        driver = create_driver(tenant, name="Rasoa", consent_geolocation=True)
        no_consent_driver = create_driver(tenant, name="Naina", consent_geolocation=False)
        return tenant, vehicle, driver, no_consent_driver


def test_create_trip_with_stops_in_order(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant,
            vehicle=vehicle,
            driver=driver,
            date=dt.date.today(),
            stops=[{"address": "Client A"}, {"address": "Client B"}],
        )
        stops = list(trip.stops.order_by("sequence"))
        assert [s.address for s in stops] == ["Client A", "Client B"]
        assert [s.sequence for s in stops] == [1, 2]


def test_create_trip_requires_at_least_one_stop(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_trip(tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[])


def test_suggest_stop_order_nearest_neighbor() -> None:
    stops = [
        {"address": "Depot", "latitude": Decimal("0"), "longitude": Decimal("0")},
        {"address": "Loin", "latitude": Decimal("10"), "longitude": Decimal("10")},
        {"address": "Proche", "latitude": Decimal("1"), "longitude": Decimal("1")},
    ]
    order = suggest_stop_order(stops)
    assert order == [0, 2, 1]


def test_suggest_stop_order_keeps_stops_without_coordinates_at_the_end() -> None:
    stops = [
        {"address": "Depot", "latitude": Decimal("0"), "longitude": Decimal("0")},
        {"address": "Sans coordonnees"},
        {"address": "Proche", "latitude": Decimal("1"), "longitude": Decimal("1")},
    ]
    order = suggest_stop_order(stops)
    assert order == [0, 2, 1]


def test_reorder_stops_applies_new_sequence(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant,
            vehicle=vehicle,
            driver=driver,
            date=dt.date.today(),
            stops=[{"address": "A"}, {"address": "B"}, {"address": "C"}],
        )
        stop_a, stop_b, stop_c = list(trip.stops.order_by("sequence"))

        reorder_stops(trip, [stop_c.id, stop_a.id, stop_b.id])

        stops = list(trip.stops.order_by("sequence"))
        assert [s.address for s in stops] == ["C", "A", "B"]


def test_reorder_stops_rejects_mismatched_set(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        with pytest.raises(ValidationError):
            reorder_stops(trip, [])


def test_record_stop_completion_without_consent_never_stores_position(trip_setup) -> None:
    tenant, vehicle, _, no_consent_driver = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant,
            vehicle=vehicle,
            driver=no_consent_driver,
            date=dt.date.today(),
            stops=[{"address": "A"}],
        )
        stop = trip.stops.first()
        record_stop_completion(
            stop,
            actual_time=dt.datetime.now(dt.UTC),
            latitude=Decimal("1"),
            longitude=Decimal("1"),
            signed_by="Client",
        )
        stop.refresh_from_db()
        assert stop.latitude is None
        assert stop.longitude is None
        assert stop.status == LogTripStop.STATUS_COMPLETED
        assert stop.signed_by == "Client"


def test_record_stop_completion_with_consent_stores_position_and_proof(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        stop = trip.stops.first()
        proof = SimpleUploadedFile("pod.jpg", b"fake-image-bytes", content_type="image/jpeg")

        record_stop_completion(
            stop,
            actual_time=dt.datetime(2026, 1, 15, 10, 0, tzinfo=dt.UTC),
            latitude=Decimal("1.5"),
            longitude=Decimal("2.5"),
            proof_file=proof,
            signed_by="Client",
        )
        stop.refresh_from_db()
        assert stop.latitude == Decimal("1.5")
        assert stop.longitude == Decimal("2.5")
        assert stop.proof_document is not None


def test_get_stop_location_masked_outside_work_hours(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        stop = trip.stops.first()
        record_stop_completion(
            stop,
            actual_time=dt.datetime(2026, 1, 15, 23, 0, tzinfo=dt.UTC),
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
        stop.refresh_from_db()
        assert get_stop_location(stop) is None


def test_get_stop_location_visible_within_work_hours(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        stop = trip.stops.first()
        record_stop_completion(
            stop,
            actual_time=dt.datetime(2026, 1, 15, 10, 0, tzinfo=dt.UTC),
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
        stop.refresh_from_db()
        assert get_stop_location(stop) == (Decimal("1"), Decimal("1"))


def test_close_trip_updates_vehicle_odometer(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        start_trip(trip, start_odometer_km=Decimal("1000"))
        close_trip(trip, end_odometer_km=Decimal("1150"))

        vehicle.refresh_from_db()
        assert vehicle.odometer_km == Decimal("1150")
        trip.refresh_from_db()
        assert trip.status == "completed"


def test_close_trip_rejects_end_before_start(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        start_trip(trip, start_odometer_km=Decimal("1000"))
        with pytest.raises(ValidationError):
            close_trip(trip, end_odometer_km=Decimal("900"))


def test_close_trip_requires_start_odometer(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        trip = create_trip(
            tenant, vehicle=vehicle, driver=driver, date=dt.date.today(), stops=[{"address": "A"}]
        )
        with pytest.raises(ValidationError):
            close_trip(trip, end_odometer_km=Decimal("100"))


def test_generate_due_trip_never_auto_starts(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        template = create_trip_template(
            tenant,
            name="Tournee hebdo",
            vehicle=vehicle,
            driver=driver,
            interval=LogTripTemplate.INTERVAL_WEEKLY,
            stops_data=[{"address": "Depot"}, {"address": "Client A"}],
            start_date=dt.date(2026, 1, 1),
        )

        trip = generate_due_trip(template, today=dt.date(2026, 1, 1))

        assert trip is not None
        assert trip.status == "planned"
        assert trip.stops.count() == 2
        template.refresh_from_db()
        assert template.next_run == dt.date(2026, 1, 8)


def test_generate_due_trip_returns_none_before_due_date(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        template = create_trip_template(
            tenant,
            name="Tournee hebdo",
            vehicle=vehicle,
            driver=driver,
            interval=LogTripTemplate.INTERVAL_WEEKLY,
            stops_data=[{"address": "Depot"}],
            start_date=dt.date(2026, 2, 1),
        )
        assert generate_due_trip(template, today=dt.date(2026, 1, 15)) is None


def test_generate_due_trip_returns_none_when_inactive(trip_setup) -> None:
    tenant, vehicle, driver, _ = trip_setup
    with use_tenant(tenant.id):
        template = create_trip_template(
            tenant,
            name="Tournee hebdo",
            vehicle=vehicle,
            driver=driver,
            interval=LogTripTemplate.INTERVAL_WEEKLY,
            stops_data=[{"address": "Depot"}],
            start_date=dt.date(2026, 1, 1),
        )
        template.is_active = False
        template.save(update_fields=["is_active"])
        assert generate_due_trip(template, today=dt.date(2026, 1, 1)) is None
