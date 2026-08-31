"""Ecrans de configuration/master-data du module `mrp` (U3), regroupes
sous le hub "Parametres" (cf. decision de placement, plan Lot 2)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.views.tenant_web import resolve_tenant
from apps.mrp.models import (
    MrpBom,
    MrpOperation,
    MrpRouting,
    MrpRoutingStep,
    MrpWorkcenter,
    MrpWorkshop,
)
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom, new_version


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "mrp/config_index.html", {})


@login_required
def config_workshops(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            workshop = MrpWorkshop(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                address=request.POST.get("address", ""),
                capacity_hours_day=Decimal(request.POST.get("capacity_hours_day") or "8"),
                is_subcontractor=bool(request.POST.get("is_subcontractor")),
            )
            workshop.full_clean()
            workshop.save()
        except (ValidationError, InvalidOperation, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_workshops")

    workshops = MrpWorkshop.objects.filter(tenant=tenant, is_active=True)
    return render(request, "mrp/config_workshops.html", {"workshops": workshops, "error": error})


@login_required
def config_workcenters(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            workshop = get_object_or_404(MrpWorkshop, id=request.POST.get("workshop_id"))
            workcenter = MrpWorkcenter(
                tenant=tenant,
                workshop=workshop,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                type=request.POST.get("type", ""),
                capacity_units_hour=Decimal(request.POST.get("capacity_units_hour") or "0"),
                cost_per_hour_mga=Decimal(request.POST.get("cost_per_hour_mga") or "0"),
            )
            workcenter.full_clean()
            workcenter.save()
        except (ValidationError, InvalidOperation, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_workcenters")

    workcenters = MrpWorkcenter.objects.filter(tenant=tenant, is_active=True)
    workshops = MrpWorkshop.objects.filter(tenant=tenant, is_active=True).order_by("code")
    default_workshop = workshops.first()
    return render(
        request,
        "mrp/config_workcenters.html",
        {
            "workcenters": workcenters,
            "workshops": workshops,
            "default_workshop_id": default_workshop.id if default_workshop else None,
            "error": error,
        },
    )


@login_required
def config_operations(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            operation = MrpOperation(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                workcenter_type=request.POST.get("workcenter_type", ""),
                default_duration_min=int(request.POST.get("default_duration_min") or "0"),
                description=request.POST.get("description", ""),
            )
            operation.full_clean()
            operation.save()
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_operations")

    operations = MrpOperation.objects.filter(tenant=tenant, is_active=True)
    return render(request, "mrp/config_operations.html", {"operations": operations, "error": error})


@login_required
def config_routings(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            routing = MrpRouting(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
            )
            routing.full_clean()
            routing.save()
        except (ValidationError, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_routings")

    routings = MrpRouting.objects.filter(tenant=tenant, is_active=True)
    return render(request, "mrp/config_routings.html", {"routings": routings, "error": error})


@login_required
def config_routing_detail(request: HttpRequest, routing_id: str) -> HttpResponse:
    routing = get_object_or_404(MrpRouting, id=routing_id)
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            operation = get_object_or_404(MrpOperation, id=request.POST.get("operation_id"))
            workcenter = get_object_or_404(MrpWorkcenter, id=request.POST.get("workcenter_id"))
            step = MrpRoutingStep(
                tenant=tenant,
                routing=routing,
                sequence=int(request.POST.get("sequence") or "0"),
                operation=operation,
                workcenter=workcenter,
                duration_min=int(request.POST.get("duration_min") or "0"),
            )
            step.full_clean()
            step.save()
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_routing_detail", routing_id=routing.id)

    operations = MrpOperation.objects.filter(tenant=tenant, is_active=True).order_by("code")
    workcenters = MrpWorkcenter.objects.filter(tenant=tenant, is_active=True).order_by("code")
    default_operation = operations.first()
    default_workcenter = workcenters.first()
    return render(
        request,
        "mrp/config_routing_detail.html",
        {
            "routing": routing,
            "steps": routing.steps.all(),
            "operations": operations,
            "workcenters": workcenters,
            "default_operation_id": default_operation.id if default_operation else None,
            "default_workcenter_id": default_workcenter.id if default_workcenter else None,
            "error": error,
        },
    )


@login_required
def config_boms(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            bom = create_bom(
                tenant=tenant,
                code=request.POST.get("code", ""),
                product_template_id=request.POST.get("product_template_id", ""),
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_bom_detail", bom_id=bom.id)

    boms = MrpBom.objects.filter(tenant=tenant, is_active=True)
    return render(request, "mrp/config_boms.html", {"boms": boms, "error": error})


@login_required
def config_bom_detail(request: HttpRequest, bom_id: str) -> HttpResponse:
    bom = get_object_or_404(MrpBom, id=bom_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "add_line":
                add_bom_line(
                    bom,
                    component_template_id=request.POST.get("component_template_id", ""),
                    qty=Decimal(request.POST.get("qty") or "1"),
                    waste_pct=Decimal(request.POST.get("waste_pct") or "0"),
                    sequence=int(request.POST.get("sequence") or "0"),
                )
            elif action == "activate":
                activate_bom(bom)
            elif action == "new_version":
                new_bom = new_version(bom)
                return redirect("mrp:config_bom_detail", bom_id=new_bom.id)
        except (ValidationError, InvalidOperation, ValueError, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:config_bom_detail", bom_id=bom.id)

    return render(
        request,
        "mrp/config_bom_detail.html",
        {"bom": bom, "lines": bom.lines.all(), "error": error},
    )
