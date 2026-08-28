"""API django-ninja du module `logistics` (§5.7, LOG7 — dernier lot de
`logistics`) : expose les services deja construits LOG1-LOG6 (vehicules,
trajets, emballages/fret, expeditions FSM, douane, webhook transporteur).
Aucune nouvelle logique metier ici — uniquement schemas de requete,
serialisation et cablage des permissions, meme discipline que
`apps.purchase.api`/`apps.stocks.api` (le module le plus recemment
termine, pris comme gabarit principal).

Le webhook transporteur (`POST /logistics/webhooks/carrier/{provider_id}`)
est le seul endpoint public (`auth=None`, verifie par signature HMAC
`services/webhooks.py::verify_carrier_webhook_signature` plutot que par
JWT applicatif) — meme patron que le webhook WhatsApp de
`apps.core.api_notifications`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import File, Form, Router, Schema
from ninja.files import UploadedFile

from apps.core.services.permissions import require_permission
from apps.core.services.workflow import TransitionPermissionError
from apps.logistics.models import (
    LogCustomsFile,
    LogCustomsLine,
    LogDriver,
    LogFreightTariff,
    LogHsCode,
    LogPackagingPlan,
    LogPackagingType,
    LogServiceProvider,
    LogShipment,
    LogTrip,
    LogTripStop,
    LogTripTemplate,
    LogVehicle,
    LogVehicleCost,
    LogVehicleDocument,
)
from apps.logistics.services.customs import (
    add_customs_line,
    close_customs_file,
    create_customs_file,
    create_hs_code,
    mark_customs_file_cleared,
    report_shipment_delay,
    simulate_customs_duties,
)
from apps.logistics.services.freight import (
    compare_freight_tariffs,
    create_freight_tariff,
    create_service_provider,
)
from apps.logistics.services.packaging import compute_packaging_plan
from apps.logistics.services.shipments import (
    add_shipment_leg,
    block_shipment,
    book_shipment,
    close_shipment,
    create_shipment,
    deliver_shipment,
    mark_shipment_arrived_at_port,
    mark_shipment_customs_cleared,
    mark_shipment_in_transit,
    pick_up_shipment,
    refactor_freight_to_customer,
    start_shipment_customs_clearance,
    unblock_shipment,
)
from apps.logistics.services.trips import (
    close_trip,
    create_trip,
    create_trip_template,
    record_stop_completion,
    reorder_stops,
    start_trip,
)
from apps.logistics.services.vehicles import (
    add_vehicle_document,
    create_driver,
    create_vehicle,
    record_vehicle_cost,
)
from apps.logistics.services.webhooks import verify_carrier_webhook_signature

router = Router(tags=["logistics"])


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# et `@require_permission(...)` l'INTERNE (juste au-dessus de `def`) — cf.
# `apps.core.services.permissions.require_permission`, meme discipline que
# `apps.purchase.api`.


def _error_response(exc: Exception) -> JsonResponse:
    message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return JsonResponse({"detail": message}, status=400)


# ---------------------------------------------------------------------------
# LOG1 — Vehicules, documents vehicule, couts, chauffeurs
# ---------------------------------------------------------------------------


class VehicleIn(Schema):
    plate_number: str
    type: str = LogVehicle.TYPE_TRUCK
    capacity_kg: Decimal | None = None
    capacity_m3: Decimal | None = None


class VehicleDocumentIn(Schema):
    doc_type: str
    reference: str = ""
    issue_date: dt.date | None = None
    expiry_date: dt.date | None = None
    alert_days_before: int = 30


class VehicleCostIn(Schema):
    date: dt.date
    cost_type: str
    amount_mga: Decimal
    odometer_km: Decimal | None = None
    note: str = ""


class DriverIn(Schema):
    name: str
    phone: str = ""
    license_number: str = ""
    license_expiry: dt.date | None = None
    consent_geolocation: bool = False


def _serialize_vehicle_document(document: LogVehicleDocument) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "doc_type": document.doc_type,
        "reference": document.reference,
        "issue_date": document.issue_date,
        "expiry_date": document.expiry_date,
        "alert_days_before": document.alert_days_before,
        "notified_at": document.notified_at,
    }


def _serialize_vehicle_cost(cost: LogVehicleCost) -> dict[str, Any]:
    return {
        "id": str(cost.id),
        "date": cost.date,
        "cost_type": cost.cost_type,
        "amount_mga": cost.amount_mga,
        "odometer_km": cost.odometer_km,
        "note": cost.note,
    }


def _serialize_vehicle(vehicle: LogVehicle) -> dict[str, Any]:
    return {
        "id": str(vehicle.id),
        "plate_number": vehicle.plate_number,
        "type": vehicle.type,
        "status": vehicle.status,
        "capacity_kg": vehicle.capacity_kg,
        "capacity_m3": vehicle.capacity_m3,
        "odometer_km": vehicle.odometer_km,
        "documents": [
            _serialize_vehicle_document(document) for document in vehicle.documents.all()
        ],
        "costs": [_serialize_vehicle_cost(cost) for cost in vehicle.costs.all()],
    }


def _serialize_driver(driver: LogDriver) -> dict[str, Any]:
    return {
        "id": str(driver.id),
        "name": driver.name,
        "phone": driver.phone,
        "license_number": driver.license_number,
        "license_expiry": driver.license_expiry,
        "consent_geolocation": driver.consent_geolocation,
    }


@router.get("/logistics/vehicles")
@require_permission("logistics.view_logvehicle")
def list_vehicles(request):
    vehicles = LogVehicle.objects.filter(is_active=True).order_by("plate_number")
    return {"results": [_serialize_vehicle(vehicle) for vehicle in vehicles]}


@router.post("/logistics/vehicles")
@require_permission("logistics.add_logvehicle")
def create_vehicle_endpoint(request, payload: VehicleIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        vehicle = create_vehicle(
            tenant,
            plate_number=payload.plate_number,
            type=payload.type,
            capacity_kg=payload.capacity_kg,
            capacity_m3=payload.capacity_m3,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_vehicle(vehicle)


@router.get("/logistics/vehicles/{vehicle_id}")
@require_permission("logistics.view_logvehicle")
def get_vehicle_endpoint(request, vehicle_id: str):
    vehicle = get_object_or_404(LogVehicle, id=vehicle_id)
    return _serialize_vehicle(vehicle)


@router.post("/logistics/vehicles/{vehicle_id}/documents")
@require_permission("logistics.add_logvehicledocument")
def add_vehicle_document_endpoint(request, vehicle_id: str, payload: VehicleDocumentIn):
    vehicle = get_object_or_404(LogVehicle, id=vehicle_id)
    try:
        document = add_vehicle_document(
            vehicle,
            doc_type=payload.doc_type,
            reference=payload.reference,
            issue_date=payload.issue_date,
            expiry_date=payload.expiry_date,
            alert_days_before=payload.alert_days_before,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_vehicle_document(document)


@router.post("/logistics/vehicles/{vehicle_id}/costs")
@require_permission("logistics.add_logvehiclecost")
def record_vehicle_cost_endpoint(request, vehicle_id: str, payload: VehicleCostIn):
    vehicle = get_object_or_404(LogVehicle, id=vehicle_id)
    try:
        cost = record_vehicle_cost(
            vehicle,
            date=payload.date,
            cost_type=payload.cost_type,
            amount_mga=payload.amount_mga,
            odometer_km=payload.odometer_km,
            note=payload.note,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_vehicle_cost(cost)


@router.get("/logistics/drivers")
@require_permission("logistics.view_logdriver")
def list_drivers(request):
    drivers = LogDriver.objects.filter(is_active=True).order_by("name")
    return {"results": [_serialize_driver(driver) for driver in drivers]}


@router.post("/logistics/drivers")
@require_permission("logistics.add_logdriver")
def create_driver_endpoint(request, payload: DriverIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        driver = create_driver(
            tenant,
            name=payload.name,
            phone=payload.phone,
            license_number=payload.license_number,
            license_expiry=payload.license_expiry,
            consent_geolocation=payload.consent_geolocation,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_driver(driver)


# ---------------------------------------------------------------------------
# LOG2 — Trajets/arrets, gabarits de tournee recurrente
# ---------------------------------------------------------------------------


class TripStopIn(Schema):
    address: str
    type: str = LogTripStop.TYPE_DROPOFF
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    planned_time: dt.datetime | None = None


class TripIn(Schema):
    vehicle_id: str
    driver_id: str
    date: dt.date
    stops: list[TripStopIn] = []


class ReorderStopsIn(Schema):
    ordered_stop_ids: list[str]


class StartTripIn(Schema):
    start_odometer_km: Decimal


class CloseTripIn(Schema):
    end_odometer_km: Decimal


class TripTemplateIn(Schema):
    name: str
    vehicle_id: str
    driver_id: str
    interval: str = LogTripTemplate.INTERVAL_WEEKLY
    stops_data: list[dict[str, Any]] = []
    start_date: dt.date
    end_date: dt.date | None = None


def _serialize_trip_stop(stop: LogTripStop) -> dict[str, Any]:
    return {
        "id": str(stop.id),
        "sequence": stop.sequence,
        "type": stop.type,
        "address": stop.address,
        "latitude": stop.latitude,
        "longitude": stop.longitude,
        "planned_time": stop.planned_time,
        "actual_time": stop.actual_time,
        "status": stop.status,
        "proof_document_id": str(stop.proof_document_id) if stop.proof_document_id else None,
        "signed_by": stop.signed_by,
    }


def _serialize_trip(trip: LogTrip) -> dict[str, Any]:
    return {
        "id": str(trip.id),
        "reference": trip.reference,
        "vehicle_id": str(trip.vehicle_id),
        "driver_id": str(trip.driver_id),
        "date": trip.date,
        "status": trip.status,
        "start_odometer_km": trip.start_odometer_km,
        "end_odometer_km": trip.end_odometer_km,
        "stops": [_serialize_trip_stop(stop) for stop in trip.stops.all()],
    }


def _serialize_trip_template(template: LogTripTemplate) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "name": template.name,
        "vehicle_id": str(template.vehicle_id),
        "driver_id": str(template.driver_id),
        "interval": template.interval,
        "stops_data": template.stops_data,
        "next_run": template.next_run,
        "end_date": template.end_date,
    }


@router.get("/logistics/trips")
@require_permission("logistics.view_logtrip")
def list_trips(request):
    trips = LogTrip.objects.filter(is_active=True).order_by("-date")
    return {"results": [_serialize_trip(trip) for trip in trips]}


@router.post("/logistics/trips")
@require_permission("logistics.add_logtrip")
def create_trip_endpoint(request, payload: TripIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    vehicle = get_object_or_404(LogVehicle, id=payload.vehicle_id)
    driver = get_object_or_404(LogDriver, id=payload.driver_id)
    try:
        trip = create_trip(
            tenant,
            vehicle=vehicle,
            driver=driver,
            date=payload.date,
            stops=[stop.model_dump() for stop in payload.stops],
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_trip(trip)


@router.get("/logistics/trips/{trip_id}")
@require_permission("logistics.view_logtrip")
def get_trip_endpoint(request, trip_id: str):
    trip = get_object_or_404(LogTrip, id=trip_id)
    return _serialize_trip(trip)


@router.post("/logistics/trips/{trip_id}/reorder-stops")
@require_permission("logistics.change_logtrip")
def reorder_stops_endpoint(request, trip_id: str, payload: ReorderStopsIn):
    trip = get_object_or_404(LogTrip, id=trip_id)
    try:
        reorder_stops(trip, [uuid.UUID(stop_id) for stop_id in payload.ordered_stop_ids])
    except ValidationError as exc:
        return _error_response(exc)
    trip.refresh_from_db()
    return _serialize_trip(trip)


@router.post("/logistics/trips/{trip_id}/start")
@require_permission("logistics.change_logtrip")
def start_trip_endpoint(request, trip_id: str, payload: StartTripIn):
    trip = get_object_or_404(LogTrip, id=trip_id)
    try:
        start_trip(trip, start_odometer_km=payload.start_odometer_km)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_trip(trip)


@router.post("/logistics/trips/{trip_id}/close")
@require_permission("logistics.change_logtrip")
def close_trip_endpoint(request, trip_id: str, payload: CloseTripIn):
    trip = get_object_or_404(LogTrip, id=trip_id)
    try:
        close_trip(trip, end_odometer_km=payload.end_odometer_km)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_trip(trip)


@router.post("/logistics/trips/{trip_id}/stops/{stop_id}/complete")
@require_permission("logistics.change_logtripstop")
def complete_trip_stop_endpoint(
    request,
    trip_id: str,
    stop_id: str,
    actual_time: dt.datetime = Form(...),  # noqa: B008 — idiome django-ninja standard
    latitude: Decimal | None = Form(None),  # noqa: B008 — idiome django-ninja standard
    longitude: Decimal | None = Form(None),  # noqa: B008 — idiome django-ninja standard
    signed_by: str = Form(""),  # noqa: B008 — idiome django-ninja standard
    proof_file: UploadedFile | None = File(None),  # noqa: B008 — idiome django-ninja standard
):
    """RG-LOG-3 (preuve de livraison, upload multipart) — meme idiome
    `ninja.File`/`ninja.Form` que `apps.chat.api.create_message`."""
    stop = get_object_or_404(LogTripStop, id=stop_id, trip_id=trip_id)
    try:
        record_stop_completion(
            stop,
            actual_time=actual_time,
            latitude=latitude,
            longitude=longitude,
            proof_file=proof_file,
            signed_by=signed_by,
            uploaded_by=request.auth,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_trip_stop(stop)


@router.get("/logistics/trip-templates")
@require_permission("logistics.view_logtriptemplate")
def list_trip_templates(request):
    templates = LogTripTemplate.objects.filter(is_active=True).order_by("name")
    return {"results": [_serialize_trip_template(template) for template in templates]}


@router.post("/logistics/trip-templates")
@require_permission("logistics.add_logtriptemplate")
def create_trip_template_endpoint(request, payload: TripTemplateIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    vehicle = get_object_or_404(LogVehicle, id=payload.vehicle_id)
    driver = get_object_or_404(LogDriver, id=payload.driver_id)
    try:
        template = create_trip_template(
            tenant,
            name=payload.name,
            vehicle=vehicle,
            driver=driver,
            interval=payload.interval,
            stops_data=payload.stops_data,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_trip_template(template)


# ---------------------------------------------------------------------------
# LOG3 — Emballage, prestataires, tarifs de fret
# ---------------------------------------------------------------------------


class PackagingTypeIn(Schema):
    code: str
    name: str
    tare_weight_kg: Decimal = Decimal(0)
    max_weight_kg: Decimal | None = None
    volume_m3: Decimal | None = None


class PackagingPlanLineIn(Schema):
    variant_id: str
    qty: Decimal


class PackagingPlanIn(Schema):
    source_app_label: str
    source_model: str
    source_object_id: str
    packaging_type_id: str
    lines: list[PackagingPlanLineIn]


class ServiceProviderIn(Schema):
    code: str
    name: str
    type: str = LogServiceProvider.TYPE_CARRIER
    contact_phone: str = ""
    contact_email: str = ""


class FreightTariffIn(Schema):
    origin: str
    destination: str
    price_mga: Decimal
    transit_days: int
    price_per_kg_mga: Decimal | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


def _serialize_packaging_type(packaging_type: LogPackagingType) -> dict[str, Any]:
    return {
        "id": str(packaging_type.id),
        "code": packaging_type.code,
        "name": packaging_type.name,
        "tare_weight_kg": packaging_type.tare_weight_kg,
        "max_weight_kg": packaging_type.max_weight_kg,
        "volume_m3": packaging_type.volume_m3,
    }


def _serialize_packaging_plan(plan: LogPackagingPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "reference": plan.reference,
        "total_weight_kg": plan.total_weight_kg,
        "total_volume_m3": plan.total_volume_m3,
        "lines": [
            {
                "id": str(line.id),
                "packaging_type_id": str(line.packaging_type_id),
                "variant_id": str(line.variant_id),
                "qty_units": line.qty_units,
                "qty_packages": line.qty_packages,
            }
            for line in plan.lines.all()
        ],
    }


def _serialize_service_provider(provider: LogServiceProvider) -> dict[str, Any]:
    return {
        "id": str(provider.id),
        "code": provider.code,
        "name": provider.name,
        "type": provider.type,
        "contact_phone": provider.contact_phone,
        "contact_email": provider.contact_email,
        "has_webhook_secret": bool(provider.webhook_secret),
    }


def _serialize_freight_tariff(tariff: LogFreightTariff) -> dict[str, Any]:
    return {
        "id": str(tariff.id),
        "provider_id": str(tariff.provider_id),
        "origin": tariff.origin,
        "destination": tariff.destination,
        "price_mga": tariff.price_mga,
        "price_per_kg_mga": tariff.price_per_kg_mga,
        "transit_days": tariff.transit_days,
        "valid_from": tariff.valid_from,
        "valid_to": tariff.valid_to,
    }


@router.get("/logistics/packaging-types")
@require_permission("logistics.view_logpackagingtype")
def list_packaging_types(request):
    types = LogPackagingType.objects.filter(is_active=True).order_by("code")
    return {"results": [_serialize_packaging_type(packaging_type) for packaging_type in types]}


@router.post("/logistics/packaging-types")
@require_permission("logistics.add_logpackagingtype")
def create_packaging_type_endpoint(request, payload: PackagingTypeIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    packaging_type = LogPackagingType(
        tenant=tenant,
        code=payload.code,
        name=payload.name,
        tare_weight_kg=payload.tare_weight_kg,
        max_weight_kg=payload.max_weight_kg,
        volume_m3=payload.volume_m3,
    )
    try:
        packaging_type.full_clean()
    except ValidationError as exc:
        return _error_response(exc)
    packaging_type.save()
    return _serialize_packaging_type(packaging_type)


@router.post("/logistics/packaging-plans")
@require_permission("logistics.add_logpackagingplan")
def compute_packaging_plan_endpoint(request, payload: PackagingPlanIn):
    """Le document source est resolu depuis `source_app_label`/
    `source_model`/`source_object_id` (jamais une FK directe, cf. docstring
    de tete de `apps.logistics.models` — `LogPackagingPlan.source` est une
    reference generique). Meme idiome minimal que le reste de l'API : pas
    de schema de decouverte des types source acceptes, l'appelant connait
    deja le document qu'il vient de creer (un `LogTrip` aujourd'hui)."""
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        model = django_apps.get_model(payload.source_app_label, payload.source_model)
    except LookupError:
        return JsonResponse({"detail": _("Type de document source inconnu.")}, status=400)
    source = get_object_or_404(model, id=payload.source_object_id)
    packaging_type = get_object_or_404(LogPackagingType, id=payload.packaging_type_id)
    try:
        plan = compute_packaging_plan(
            tenant,
            source=source,
            packaging_type=packaging_type,
            lines=[{"variant_id": line.variant_id, "qty": line.qty} for line in payload.lines],
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_packaging_plan(plan)


@router.get("/logistics/packaging-plans/{plan_id}")
@require_permission("logistics.view_logpackagingplan")
def get_packaging_plan_endpoint(request, plan_id: str):
    plan = get_object_or_404(LogPackagingPlan, id=plan_id)
    return _serialize_packaging_plan(plan)


@router.get("/logistics/service-providers")
@require_permission("logistics.view_logserviceprovider")
def list_service_providers(request):
    providers = LogServiceProvider.objects.filter(is_active=True).order_by("name")
    return {"results": [_serialize_service_provider(provider) for provider in providers]}


@router.post("/logistics/service-providers")
@require_permission("logistics.add_logserviceprovider")
def create_service_provider_endpoint(request, payload: ServiceProviderIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        provider = create_service_provider(
            tenant,
            code=payload.code,
            name=payload.name,
            type=payload.type,
            contact_phone=payload.contact_phone,
            contact_email=payload.contact_email,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_service_provider(provider)


@router.post("/logistics/service-providers/{provider_id}/freight-tariffs")
@require_permission("logistics.add_logfreighttariff")
def create_freight_tariff_endpoint(request, provider_id: str, payload: FreightTariffIn):
    provider = get_object_or_404(LogServiceProvider, id=provider_id)
    try:
        tariff = create_freight_tariff(
            provider,
            origin=payload.origin,
            destination=payload.destination,
            price_mga=payload.price_mga,
            transit_days=payload.transit_days,
            price_per_kg_mga=payload.price_per_kg_mga,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_freight_tariff(tariff)


@router.get("/logistics/freight-tariffs/compare")
@require_permission("logistics.view_logfreighttariff")
def compare_freight_tariffs_endpoint(
    request, origin: str, destination: str, weight_kg: Decimal | None = None
):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rows = compare_freight_tariffs(
        tenant, origin=origin, destination=destination, weight_kg=weight_kg
    )
    return {
        "results": [
            {
                "tariff_id": str(row["tariff_id"]),
                "provider_id": str(row["provider_id"]),
                "provider_name": row["provider_name"],
                "total_cost_mga": row["total_cost_mga"],
                "transit_days": row["transit_days"],
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# LOG4 — Expeditions (FSM complete) et refacturation fret (LOG-REFACT1)
# ---------------------------------------------------------------------------


class ShipmentLegIn(Schema):
    mode: str = "road"
    origin: str
    destination: str
    carrier_id: str | None = None
    departure_date: dt.date | None = None
    arrival_date: dt.date | None = None


class ShipmentIn(Schema):
    origin: str
    destination: str
    carrier_id: str | None = None
    incoterm: str = ""
    purchase_order_ids: list[str] = []
    sales_order_ids: list[str] = []
    legs: list[ShipmentLegIn] = []


class ShipmentBlockIn(Schema):
    reason: str


class RefactorFreightIn(Schema):
    partner_id: str
    amount_mga: Decimal | None = None
    date: dt.date | None = None


def _serialize_shipment_leg(leg) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "id": str(leg.id),
        "sequence": leg.sequence,
        "mode": leg.mode,
        "origin": leg.origin,
        "destination": leg.destination,
        "carrier_id": str(leg.carrier_id) if leg.carrier_id else None,
        "departure_date": leg.departure_date,
        "arrival_date": leg.arrival_date,
    }


def _serialize_shipment(shipment: LogShipment) -> dict[str, Any]:
    return {
        "id": str(shipment.id),
        "reference": shipment.reference,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "carrier_id": str(shipment.carrier_id) if shipment.carrier_id else None,
        "incoterm": shipment.incoterm,
        "purchase_order_ids": shipment.purchase_order_ids,
        "sales_order_ids": shipment.sales_order_ids,
        "weight_kg": shipment.weight_kg,
        "volume_m3": shipment.volume_m3,
        "freight_cost_mga": shipment.freight_cost_mga,
        "freight_billed_to_customer_mga": shipment.freight_billed_to_customer_mga,
        "state": shipment.state,
        "block_reason": shipment.block_reason,
        "legs": [_serialize_shipment_leg(leg) for leg in shipment.legs.all()],
    }


def _handle_shipment_errors(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
    try:
        return fn(*args, **kwargs), None
    except (ValidationError, TransitionPermissionError) as exc:
        return None, _error_response(exc)


@router.get("/logistics/shipments")
@require_permission("logistics.view_logshipment")
def list_shipments(request):
    shipments = LogShipment.objects.filter(is_active=True).order_by("-created_at")
    return {"results": [_serialize_shipment(shipment) for shipment in shipments]}


@router.post("/logistics/shipments")
@require_permission("logistics.add_logshipment")
def create_shipment_endpoint(request, payload: ShipmentIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    carrier = (
        get_object_or_404(LogServiceProvider, id=payload.carrier_id) if payload.carrier_id else None
    )
    try:
        shipment = create_shipment(
            tenant,
            origin=payload.origin,
            destination=payload.destination,
            carrier=carrier,
            incoterm=payload.incoterm,
            purchase_order_ids=payload.purchase_order_ids,
            sales_order_ids=payload.sales_order_ids,
        )
        for leg in payload.legs:
            leg_carrier = (
                get_object_or_404(LogServiceProvider, id=leg.carrier_id) if leg.carrier_id else None
            )
            add_shipment_leg(
                shipment,
                mode=leg.mode,
                origin=leg.origin,
                destination=leg.destination,
                carrier=leg_carrier,
                departure_date=leg.departure_date,
                arrival_date=leg.arrival_date,
            )
    except ValidationError as exc:
        return _error_response(exc)
    shipment.refresh_from_db()
    return _serialize_shipment(shipment)


@router.get("/logistics/shipments/{shipment_id}")
@require_permission("logistics.view_logshipment")
def get_shipment_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    return _serialize_shipment(shipment)


@router.post("/logistics/shipments/{shipment_id}/legs")
@require_permission("logistics.change_logshipment")
def add_shipment_leg_endpoint(request, shipment_id: str, payload: ShipmentLegIn):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    carrier = (
        get_object_or_404(LogServiceProvider, id=payload.carrier_id) if payload.carrier_id else None
    )
    try:
        add_shipment_leg(
            shipment,
            mode=payload.mode,
            origin=payload.origin,
            destination=payload.destination,
            carrier=carrier,
            departure_date=payload.departure_date,
            arrival_date=payload.arrival_date,
        )
    except ValidationError as exc:
        return _error_response(exc)
    shipment.refresh_from_db()
    return _serialize_shipment(shipment)


@router.post("/logistics/shipments/{shipment_id}/book")
@require_permission("logistics.change_logshipment")
def book_shipment_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(book_shipment, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/pick-up")
@require_permission("logistics.change_logshipment")
def pick_up_shipment_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(pick_up_shipment, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/mark-in-transit")
@require_permission("logistics.change_logshipment")
def mark_shipment_in_transit_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(mark_shipment_in_transit, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/mark-arrived-at-port")
@require_permission("logistics.change_logshipment")
def mark_shipment_arrived_at_port_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(mark_shipment_arrived_at_port, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/start-customs-clearance")
@require_permission("logistics.change_logshipment")
def start_shipment_customs_clearance_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(
        start_shipment_customs_clearance, shipment, request.auth
    )
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/mark-customs-cleared")
@require_permission("logistics.change_logshipment")
def mark_shipment_customs_cleared_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(mark_shipment_customs_cleared, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/deliver")
@require_permission("logistics.change_logshipment")
def deliver_shipment_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(deliver_shipment, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/close")
@require_permission("logistics.change_logshipment")
def close_shipment_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(close_shipment, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/unblock")
@require_permission("logistics.change_logshipment")
def unblock_shipment_endpoint(request, shipment_id: str):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(unblock_shipment, shipment, request.auth)
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/block")
@require_permission("logistics.change_logshipment")
def block_shipment_endpoint(request, shipment_id: str, payload: ShipmentBlockIn):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    result, error = _handle_shipment_errors(
        block_shipment, shipment, request.auth, reason=payload.reason
    )
    if error is not None:
        return error
    return _serialize_shipment(result)


@router.post("/logistics/shipments/{shipment_id}/refactor-freight")
@require_permission("logistics.change_logshipment")
def refactor_freight_endpoint(request, shipment_id: str, payload: RefactorFreightIn):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    invoice_id = refactor_freight_to_customer(
        shipment,
        partner_id=uuid.UUID(payload.partner_id),
        amount_mga=payload.amount_mga,
        date=payload.date,
    )
    return {"invoice_id": str(invoice_id) if invoice_id else None}


class ShipmentDelayIn(Schema):
    expected_date: dt.date
    supplier_partner_id: str
    as_of: dt.date | None = None
    threshold_days: int = 3


@router.post("/logistics/shipments/{shipment_id}/report-delay")
@require_permission("logistics.change_logshipment")
def report_shipment_delay_endpoint(request, shipment_id: str, payload: ShipmentDelayIn):
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    incident_id = report_shipment_delay(
        shipment,
        expected_date=payload.expected_date,
        supplier_partner_id=uuid.UUID(payload.supplier_partner_id),
        as_of=payload.as_of,
        threshold_days=payload.threshold_days,
    )
    return {"incident_id": str(incident_id) if incident_id else None}


# ---------------------------------------------------------------------------
# LOG5 — Douane : codes SH, dossier douanier, calculateur RG-LOG-6
# ---------------------------------------------------------------------------


class HsCodeIn(Schema):
    code: str
    description: str
    duty_rate_pct: Decimal
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


class CustomsFileIn(Schema):
    shipment_id: str
    broker_id: str | None = None
    opened_at: dt.date | None = None


class CustomsLineIn(Schema):
    hs_code_id: str
    description: str
    fob_value_mga: Decimal
    freight_value_mga: Decimal = Decimal(0)
    insurance_value_mga: Decimal = Decimal(0)
    other_non_recoverable_taxes_mga: Decimal = Decimal(0)
    transit_cost_mga: Decimal = Decimal(0)
    qty: Decimal = Decimal(1)
    weight_kg: Decimal | None = None
    variant_id: str | None = None


class CustomsSimulateIn(Schema):
    fob_value_mga: Decimal
    duty_rate_pct: Decimal
    freight_value_mga: Decimal = Decimal(0)
    insurance_value_mga: Decimal = Decimal(0)
    other_non_recoverable_taxes_mga: Decimal = Decimal(0)
    transit_cost_mga: Decimal = Decimal(0)
    vat_rate_pct: Decimal = Decimal("20")


def _serialize_hs_code(hs_code: LogHsCode) -> dict[str, Any]:
    return {
        "id": str(hs_code.id),
        "code": hs_code.code,
        "description": hs_code.description,
        "duty_rate_pct": hs_code.duty_rate_pct,
        "valid_from": hs_code.valid_from,
        "valid_to": hs_code.valid_to,
    }


def _serialize_customs_line(line: LogCustomsLine) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "hs_code_id": str(line.hs_code_id),
        "description": line.description,
        "variant_id": str(line.variant_id) if line.variant_id else None,
        "qty": line.qty,
        "weight_kg": line.weight_kg,
        "fob_value_mga": line.fob_value_mga,
        "freight_value_mga": line.freight_value_mga,
        "insurance_value_mga": line.insurance_value_mga,
        "other_non_recoverable_taxes_mga": line.other_non_recoverable_taxes_mga,
        "transit_cost_mga": line.transit_cost_mga,
        "caf_value_mga": line.caf_value_mga,
        "duty_mga": line.duty_mga,
        "vat_base_mga": line.vat_base_mga,
        "vat_mga": line.vat_mga,
        "landed_cost_mga": line.landed_cost_mga,
    }


def _serialize_customs_file(customs_file: LogCustomsFile) -> dict[str, Any]:
    return {
        "id": str(customs_file.id),
        "reference": customs_file.reference,
        "shipment_id": str(customs_file.shipment_id),
        "broker_id": str(customs_file.broker_id) if customs_file.broker_id else None,
        "state": customs_file.state,
        "opened_at": customs_file.opened_at,
        "cleared_at": customs_file.cleared_at,
        "closed_at": customs_file.closed_at,
        "landed_cost_batch_id": str(customs_file.landed_cost_batch_id)
        if customs_file.landed_cost_batch_id
        else None,
        "lines": [_serialize_customs_line(line) for line in customs_file.lines.all()],
    }


@router.get("/logistics/hs-codes")
@require_permission("logistics.view_loghscode")
def list_hs_codes(request):
    codes = LogHsCode.objects.filter(is_active=True).order_by("code")
    return {"results": [_serialize_hs_code(hs_code) for hs_code in codes]}


@router.post("/logistics/hs-codes")
@require_permission("logistics.add_loghscode")
def create_hs_code_endpoint(request, payload: HsCodeIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        hs_code = create_hs_code(
            tenant,
            code=payload.code,
            description=payload.description,
            duty_rate_pct=payload.duty_rate_pct,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_hs_code(hs_code)


@router.post("/logistics/customs/simulate")
@require_permission("logistics.view_logcustomsline")
def simulate_customs_endpoint(request, payload: CustomsSimulateIn):
    """Calculateur pur (RG-LOG-6) — apercu SANS persistance, cf.
    `services/customs.py::simulate_customs_duties`."""
    result = simulate_customs_duties(
        fob_value_mga=payload.fob_value_mga,
        duty_rate_pct=payload.duty_rate_pct,
        freight_value_mga=payload.freight_value_mga,
        insurance_value_mga=payload.insurance_value_mga,
        other_non_recoverable_taxes_mga=payload.other_non_recoverable_taxes_mga,
        transit_cost_mga=payload.transit_cost_mga,
        vat_rate_pct=payload.vat_rate_pct,
    )
    return {key: value for key, value in result.items()}


@router.post("/logistics/customs-files")
@require_permission("logistics.add_logcustomsfile")
def create_customs_file_endpoint(request, payload: CustomsFileIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    shipment = get_object_or_404(LogShipment, id=payload.shipment_id)
    broker = (
        get_object_or_404(LogServiceProvider, id=payload.broker_id) if payload.broker_id else None
    )
    try:
        customs_file = create_customs_file(
            tenant, shipment=shipment, broker=broker, opened_at=payload.opened_at
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_customs_file(customs_file)


@router.get("/logistics/customs-files/{customs_file_id}")
@require_permission("logistics.view_logcustomsfile")
def get_customs_file_endpoint(request, customs_file_id: str):
    customs_file = get_object_or_404(LogCustomsFile, id=customs_file_id)
    return _serialize_customs_file(customs_file)


@router.post("/logistics/customs-files/{customs_file_id}/lines")
@require_permission("logistics.add_logcustomsline")
def add_customs_line_endpoint(request, customs_file_id: str, payload: CustomsLineIn):
    customs_file = get_object_or_404(LogCustomsFile, id=customs_file_id)
    hs_code = get_object_or_404(LogHsCode, id=payload.hs_code_id)
    try:
        add_customs_line(
            customs_file,
            hs_code=hs_code,
            description=payload.description,
            fob_value_mga=payload.fob_value_mga,
            freight_value_mga=payload.freight_value_mga,
            insurance_value_mga=payload.insurance_value_mga,
            other_non_recoverable_taxes_mga=payload.other_non_recoverable_taxes_mga,
            transit_cost_mga=payload.transit_cost_mga,
            qty=payload.qty,
            weight_kg=payload.weight_kg,
            variant_id=uuid.UUID(payload.variant_id) if payload.variant_id else None,
        )
    except ValidationError as exc:
        return _error_response(exc)
    customs_file.refresh_from_db()
    return _serialize_customs_file(customs_file)


@router.post("/logistics/customs-files/{customs_file_id}/mark-cleared")
@require_permission("logistics.change_logcustomsfile")
def mark_customs_file_cleared_endpoint(request, customs_file_id: str):
    customs_file = get_object_or_404(LogCustomsFile, id=customs_file_id)
    try:
        mark_customs_file_cleared(customs_file)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_customs_file(customs_file)


@router.post("/logistics/customs-files/{customs_file_id}/close")
@require_permission("logistics.change_logcustomsfile")
def close_customs_file_endpoint(request, customs_file_id: str):
    customs_file = get_object_or_404(LogCustomsFile, id=customs_file_id)
    try:
        close_customs_file(customs_file)
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_customs_file(customs_file)


# ---------------------------------------------------------------------------
# LOG6 — Webhook transporteur signe (API-6, `auth=None`)
# ---------------------------------------------------------------------------


@router.post("/logistics/webhooks/carrier/{provider_id}", auth=None)
def carrier_webhook_endpoint(request, provider_id: str):
    """Reception d'un evenement transporteur (mise a jour de statut
    d'expedition typiquement) — public (pas de JWT applicatif, c'est le
    transporteur qui appelle), authentifie par signature HMAC-SHA256
    (`X-Signature`) verifiee via `services/webhooks.py::
    verify_carrier_webhook_signature`. Ne materialise aucun changement
    d'etat automatique dans ce lot (aucune regle de mapping evenement ->
    transition FSM n'est specifiee au CDC) : la charge utile est
    uniquement journalisee/acceptee une fois la signature validee — a
    completer si un futur besoin de mapping precis se presente,
    deviation documentee plutot que devinee.

    `LogServiceProvider.all_objects` (jamais le manager `objects`, filtre
    par tenant courant) : cet endpoint est appele par le transporteur SANS
    contexte tenant applicatif (pas d'en-tete `X-Tenant-Id`, pas de session)
    — meme necessite que `apps.core.services.tenant_export`/`sandbox.py`,
    seuls autres appelants documentes de ce manager non filtre."""
    provider = get_object_or_404(LogServiceProvider.all_objects, id=provider_id)
    signature = request.headers.get("X-Signature", "")
    if not verify_carrier_webhook_signature(provider, payload=request.body, signature=signature):
        return HttpResponse(status=403)
    return {"status": "ok"}
