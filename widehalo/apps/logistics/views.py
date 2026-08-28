"""Ecrans HTMX transactionnels du module `logistics` (LOG7, §5.7 — dernier
lot de `logistics`) : vehicules (+documents/couts inline), chauffeurs,
trajets (+arrets, preuve de livraison, bandeau start/close), gabarits de
tournee, expeditions (bandeau de workflow FSM complet, legs inline,
ouverture du dossier douanier), dossier douanier (lignes, mark-cleared/
close). Meme patron que `apps.purchase.views` : session-authentifie
(`@login_required`), appel direct aux `services/*` de `logistics`, jamais
l'API JWT interne.

**Chauffeurs/gabarits de tournee** : rendus sur UNE SEULE page chacun
(liste + creation, jamais de fiche detail dediee) — meme deviation
documentee que `PurCra`/`PurCri` dans `apps.purchase.views` (cycle de vie
trivial, pas de sous-formulaire riche justifiant un gabarit separe)."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.logistics.models import (
    LogCustomsFile,
    LogDriver,
    LogHsCode,
    LogServiceProvider,
    LogShipment,
    LogTrip,
    LogTripStop,
    LogTripTemplate,
    LogVehicle,
)
from apps.logistics.services.customs import (
    add_customs_line,
    close_customs_file,
    create_customs_file,
    mark_customs_file_cleared,
)
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
    start_trip,
)
from apps.logistics.services.vehicles import (
    add_vehicle_document,
    create_driver,
    create_vehicle,
    record_vehicle_cost,
)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


_SHIPMENT_EXCEPTIONS = (ValidationError, InvalidOperation, ValueError, TransitionPermissionError)


# ---------------------------------------------------------------------------
# Vehicules, documents, couts (LOG1)
# ---------------------------------------------------------------------------

VEHICLE_COLUMNS = [
    Column(key="plate_number", label="Immatriculation"),
    Column(key="type", label="Type"),
    Column(key="status", label="Statut"),
    Column(key="odometer_km", label="Kilometrage", searchable=False),
]


@login_required
def vehicle_list(request: HttpRequest) -> HttpResponse:
    queryset = LogVehicle.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="logistics.vehicles",
        columns=VEHICLE_COLUMNS,
        queryset=queryset,
        page_template="logistics/vehicle_list.html",
        page_context={"row_url_name": "logistics:vehicle_detail"},
    )


@login_required
def vehicle_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            vehicle = create_vehicle(
                tenant,
                plate_number=request.POST.get("plate_number", ""),
                type=request.POST.get("type", LogVehicle.TYPE_TRUCK),
                capacity_kg=Decimal(request.POST["capacity_kg"])
                if request.POST.get("capacity_kg")
                else None,
                capacity_m3=Decimal(request.POST["capacity_m3"])
                if request.POST.get("capacity_m3")
                else None,
            )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:vehicle_detail", vehicle_id=vehicle.id)

    return render(
        request,
        "logistics/vehicle_create.html",
        {"error": error, "type_choices": LogVehicle.TYPE_CHOICES},
    )


@login_required
def vehicle_detail(request: HttpRequest, vehicle_id: str) -> HttpResponse:
    vehicle = get_object_or_404(LogVehicle, id=vehicle_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_document":
                add_vehicle_document(
                    vehicle,
                    doc_type=post.get("doc_type", ""),
                    reference=post.get("reference", ""),
                    issue_date=parse_date(post.get("issue_date", "")),
                    expiry_date=parse_date(post.get("expiry_date", "")),
                    alert_days_before=int(post.get("alert_days_before") or "30"),
                )
            elif action == "add_cost":
                record_vehicle_cost(
                    vehicle,
                    date=parse_date(post.get("date", "")) or timezone.now().date(),
                    cost_type=post.get("cost_type", ""),
                    amount_mga=Decimal(post.get("amount_mga") or "0"),
                    odometer_km=Decimal(post["odometer_km"]) if post.get("odometer_km") else None,
                    note=post.get("note", ""),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:vehicle_detail", vehicle_id=vehicle.id)

    return render(
        request,
        "logistics/vehicle_detail.html",
        {
            "vehicle": vehicle,
            "documents": vehicle.documents.all(),
            "costs": vehicle.costs.all().order_by("-date"),
            "doc_type_choices": vehicle.documents.model.TYPE_CHOICES,
            "cost_type_choices": vehicle.costs.model.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
def driver_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            create_driver(
                tenant,
                name=request.POST.get("name", ""),
                phone=request.POST.get("phone", ""),
                license_number=request.POST.get("license_number", ""),
                license_expiry=parse_date(request.POST.get("license_expiry", "")),
                consent_geolocation=bool(request.POST.get("consent_geolocation")),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:driver_list")

    drivers = LogDriver.objects.filter(tenant=tenant, is_active=True).order_by("name")
    return render(request, "logistics/driver_list.html", {"drivers": drivers, "error": error})


# ---------------------------------------------------------------------------
# Trajets/arrets, gabarits de tournee (LOG2)
# ---------------------------------------------------------------------------

TRIP_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="status", label="Statut"),
    Column(key="date", label="Date", searchable=False),
]


@login_required
def trip_list(request: HttpRequest) -> HttpResponse:
    queryset = LogTrip.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="logistics.trips",
        columns=TRIP_COLUMNS,
        queryset=queryset,
        page_template="logistics/trip_list.html",
        page_context={"row_url_name": "logistics:trip_detail"},
    )


@login_required
def trip_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            vehicle = get_object_or_404(LogVehicle, id=request.POST.get("vehicle_id", ""))
            driver = get_object_or_404(LogDriver, id=request.POST.get("driver_id", ""))
            addresses = [
                line.strip()
                for line in request.POST.get("stop_addresses", "").splitlines()
                if line.strip()
            ]
            trip = create_trip(
                tenant,
                vehicle=vehicle,
                driver=driver,
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                stops=[{"address": address} for address in addresses],
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:trip_detail", trip_id=trip.id)

    return render(
        request,
        "logistics/trip_create.html",
        {
            "error": error,
            "vehicles": LogVehicle.objects.filter(is_active=True),
            "drivers": LogDriver.objects.filter(is_active=True),
        },
    )


@login_required
def trip_detail(request: HttpRequest, trip_id: str) -> HttpResponse:
    trip = get_object_or_404(LogTrip, id=trip_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "start":
                start_trip(trip, start_odometer_km=Decimal(post.get("start_odometer_km") or "0"))
            elif action == "close":
                close_trip(trip, end_odometer_km=Decimal(post.get("end_odometer_km") or "0"))
            elif action == "complete_stop":
                stop = get_object_or_404(LogTripStop, id=post.get("stop_id"), trip=trip)
                record_stop_completion(
                    stop,
                    actual_time=parse_datetime(post.get("actual_time", "")) or timezone.now(),
                    latitude=Decimal(post["latitude"]) if post.get("latitude") else None,
                    longitude=Decimal(post["longitude"]) if post.get("longitude") else None,
                    proof_file=request.FILES.get("proof_file"),
                    signed_by=post.get("signed_by", ""),
                    uploaded_by=cast(User, request.user),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:trip_detail", trip_id=trip.id)

    return render(
        request,
        "logistics/trip_detail.html",
        {"trip": trip, "stops": trip.stops.all(), "error": error},
    )


@login_required
def trip_template_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            vehicle = get_object_or_404(LogVehicle, id=request.POST.get("vehicle_id", ""))
            driver = get_object_or_404(LogDriver, id=request.POST.get("driver_id", ""))
            addresses = [
                line.strip()
                for line in request.POST.get("stop_addresses", "").splitlines()
                if line.strip()
            ]
            create_trip_template(
                tenant,
                name=request.POST.get("name", ""),
                vehicle=vehicle,
                driver=driver,
                interval=request.POST.get("interval", LogTripTemplate.INTERVAL_WEEKLY),
                stops_data=[{"address": address} for address in addresses],
                start_date=parse_date(request.POST.get("start_date", "")) or timezone.now().date(),
                end_date=parse_date(request.POST.get("end_date", "")),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:trip_template_list")

    templates = LogTripTemplate.objects.filter(tenant=tenant, is_active=True).order_by("name")
    return render(
        request,
        "logistics/trip_template_list.html",
        {
            "templates": templates,
            "interval_choices": LogTripTemplate.INTERVAL_CHOICES,
            "vehicles": LogVehicle.objects.filter(is_active=True),
            "drivers": LogDriver.objects.filter(is_active=True),
            "error": error,
        },
    )


# ---------------------------------------------------------------------------
# Expeditions (LOG4, FSM complete) et dossier douanier (LOG5)
# ---------------------------------------------------------------------------

SHIPMENT_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="origin", label="Origine", searchable=False),
    Column(key="destination", label="Destination", searchable=False),
]

_SHIPMENT_ACTIONS = {
    "book": lambda shipment, user, _post: book_shipment(shipment, user),
    "pick_up": lambda shipment, user, _post: pick_up_shipment(shipment, user),
    "mark_in_transit": lambda shipment, user, _post: mark_shipment_in_transit(shipment, user),
    "mark_arrived_at_port": lambda shipment, user, _post: mark_shipment_arrived_at_port(
        shipment, user
    ),
    "start_customs_clearance": lambda shipment, user, _post: start_shipment_customs_clearance(
        shipment, user
    ),
    "mark_customs_cleared": lambda shipment, user, _post: mark_shipment_customs_cleared(
        shipment, user
    ),
    "deliver": lambda shipment, user, _post: deliver_shipment(shipment, user),
    "close": lambda shipment, user, _post: close_shipment(shipment, user),
    "unblock": lambda shipment, user, _post: unblock_shipment(shipment, user),
    "block": lambda shipment, user, post: block_shipment(
        shipment, user, reason=post.get("reason", "")
    ),
}


@login_required
def shipment_list(request: HttpRequest) -> HttpResponse:
    queryset = LogShipment.objects.filter(is_active=True)
    state = request.GET.get("state")
    if state:
        queryset = queryset.filter(state=state)
    return smart_table_response(
        request,
        table_key="logistics.shipments",
        columns=SHIPMENT_COLUMNS,
        queryset=queryset,
        page_template="logistics/shipment_list.html",
        page_context={
            "row_url_name": "logistics:shipment_detail",
            "state_choices": LogShipment.STATE_CHOICES,
            "selected_state": state or "",
        },
    )


@login_required
def shipment_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            carrier_id = request.POST.get("carrier_id", "")
            carrier = get_object_or_404(LogServiceProvider, id=carrier_id) if carrier_id else None
            shipment = create_shipment(
                tenant,
                origin=request.POST.get("origin", ""),
                destination=request.POST.get("destination", ""),
                carrier=carrier,
                incoterm=request.POST.get("incoterm", ""),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:shipment_detail", shipment_id=shipment.id)

    return render(
        request,
        "logistics/shipment_create.html",
        {
            "error": error,
            "incoterm_choices": LogShipment.INCOTERM_CHOICES,
            "carriers": LogServiceProvider.objects.filter(is_active=True),
        },
    )


@login_required
def shipment_detail(request: HttpRequest, shipment_id: str) -> HttpResponse:
    shipment = get_object_or_404(LogShipment, id=shipment_id)
    user = cast(User, request.user)
    error = None
    new_customs_file = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_leg":
                carrier_id = post.get("carrier_id", "")
                carrier = (
                    get_object_or_404(LogServiceProvider, id=carrier_id) if carrier_id else None
                )
                add_shipment_leg(
                    shipment,
                    mode=post.get("mode", "road"),
                    origin=post.get("leg_origin", ""),
                    destination=post.get("leg_destination", ""),
                    carrier=carrier,
                    departure_date=parse_date(post.get("departure_date", "")),
                    arrival_date=parse_date(post.get("arrival_date", "")),
                )
            elif action == "open_customs_file":
                broker_id = post.get("broker_id", "")
                broker = get_object_or_404(LogServiceProvider, id=broker_id) if broker_id else None
                new_customs_file = create_customs_file(
                    shipment.tenant, shipment=shipment, broker=broker
                )
            elif action == "refactor_freight":
                refactor_freight_to_customer(
                    shipment,
                    partner_id=uuid.UUID(post.get("partner_id", "")),
                    amount_mga=Decimal(post["amount_mga"]) if post.get("amount_mga") else None,
                )
            else:
                handler = _SHIPMENT_ACTIONS.get(action)
                if handler is not None:
                    handler(shipment, user, post)
        except _SHIPMENT_EXCEPTIONS as exc:
            error = _error_message(exc)
        else:
            if new_customs_file is not None:
                return redirect(
                    "logistics:customs_file_detail", customs_file_id=new_customs_file.id
                )
            return redirect("logistics:shipment_detail", shipment_id=shipment.id)

    return render(
        request,
        "logistics/shipment_detail.html",
        {
            "shipment": shipment,
            "legs": shipment.legs.all(),
            "customs_files": shipment.customs_files.all(),
            "carriers": LogServiceProvider.objects.filter(is_active=True),
            "error": error,
        },
    )


@login_required
def customs_file_detail(request: HttpRequest, customs_file_id: str) -> HttpResponse:
    customs_file = get_object_or_404(LogCustomsFile, id=customs_file_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                hs_code = get_object_or_404(LogHsCode, id=post.get("hs_code_id", ""))
                add_customs_line(
                    customs_file,
                    hs_code=hs_code,
                    description=post.get("description", ""),
                    fob_value_mga=Decimal(post.get("fob_value_mga") or "0"),
                    freight_value_mga=Decimal(post.get("freight_value_mga") or "0"),
                    insurance_value_mga=Decimal(post.get("insurance_value_mga") or "0"),
                    other_non_recoverable_taxes_mga=Decimal(
                        post.get("other_non_recoverable_taxes_mga") or "0"
                    ),
                    transit_cost_mga=Decimal(post.get("transit_cost_mga") or "0"),
                    qty=Decimal(post.get("qty") or "1"),
                    variant_id=uuid.UUID(post["variant_id"]) if post.get("variant_id") else None,
                )
            elif action == "mark_cleared":
                mark_customs_file_cleared(customs_file)
            elif action == "close":
                close_customs_file(customs_file)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:customs_file_detail", customs_file_id=customs_file.id)

    return render(
        request,
        "logistics/customs_file_detail.html",
        {
            "customs_file": customs_file,
            "lines": customs_file.lines.all(),
            "hs_codes": LogHsCode.objects.filter(is_active=True),
            "error": error,
        },
    )
