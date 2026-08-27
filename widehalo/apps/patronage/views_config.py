"""Ecrans de configuration/master-data du module `patronage` (U3),
regroupes sous le hub "Parametres" (cf. decision de placement, plan Lot 2)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.views.tenant_web import resolve_tenant
from apps.patronage.models import (
    PatGradingRule,
    PatMeasurementPoint,
    PatSizeChart,
    PatSizeChartValue,
)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "patronage/config_index.html", {})


@login_required
def config_size_charts(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            sizes = [s.strip() for s in request.POST.get("sizes", "").split(",") if s.strip()]
            size_chart = PatSizeChart(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                garment_type=request.POST.get("garment_type", ""),
                sizes=sizes,
                base_size=request.POST.get("base_size", ""),
            )
            size_chart.full_clean()
            size_chart.save()
        except (ValidationError, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("patronage:config_size_chart_detail", size_chart_id=size_chart.id)

    size_charts = PatSizeChart.objects.filter(tenant=tenant, is_active=True)
    return render(
        request, "patronage/config_size_charts.html", {"size_charts": size_charts, "error": error}
    )


@login_required
def config_size_chart_detail(request: HttpRequest, size_chart_id: str) -> HttpResponse:
    size_chart = get_object_or_404(PatSizeChart, id=size_chart_id)
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "add_measurement_point":
                point = PatMeasurementPoint(
                    tenant=tenant,
                    code=request.POST.get("code", ""),
                    name=request.POST.get("name", ""),
                    unit=request.POST.get("unit", PatMeasurementPoint.UNIT_CM),
                    category=request.POST.get("category", PatMeasurementPoint.CATEGORY_LENGTH),
                )
                point.full_clean()
                point.save()
            elif action == "add_value":
                measurement_point = get_object_or_404(
                    PatMeasurementPoint, id=request.POST.get("measurement_point_id")
                )
                value, _created = PatSizeChartValue.objects.update_or_create(
                    tenant=tenant,
                    size_chart=size_chart,
                    measurement_point=measurement_point,
                    size=request.POST.get("size", ""),
                    defaults={"value": Decimal(request.POST.get("value") or "0")},
                )
                value.full_clean()
        except (ValidationError, InvalidOperation, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("patronage:config_size_chart_detail", size_chart_id=size_chart.id)

    measurement_points = PatMeasurementPoint.objects.filter(tenant=tenant, is_active=True)
    values = size_chart.values.select_related("measurement_point").all()
    return render(
        request,
        "patronage/config_size_chart_detail.html",
        {
            "size_chart": size_chart,
            "measurement_points": measurement_points,
            "values": values,
            "error": error,
        },
    )


@login_required
def config_grading_rules(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            size_chart = get_object_or_404(PatSizeChart, id=request.POST.get("size_chart_id"))
            measurement_point = get_object_or_404(
                PatMeasurementPoint, id=request.POST.get("measurement_point_id")
            )
            mode = request.POST.get("mode", "")
            # Simplification volontaire (U3) : un seul formulaire generique
            # couvre les 4 modes. `value` porte l'increment/le pourcentage
            # (modes fixe/progressif/pourcentage) ; `formula` ne sert qu'au
            # mode `formule`. Pas de formulaire dynamique par mode.
            value_raw = request.POST.get("value", "").strip()
            rule = PatGradingRule(
                tenant=tenant,
                size_chart=size_chart,
                measurement_point=measurement_point,
                mode=mode,
                value=Decimal(value_raw) if value_raw else None,
                formula=request.POST.get("formula", ""),
                from_size=request.POST.get("from_size", ""),
                to_size=request.POST.get("to_size", ""),
            )
            rule.full_clean()
            rule.save()
        except (ValidationError, InvalidOperation, IntegrityError) as exc:
            error = _error_message(exc)
        else:
            return redirect("patronage:config_grading_rules")

    grading_rules = PatGradingRule.objects.filter(tenant=tenant, is_active=True)
    size_charts = PatSizeChart.objects.filter(tenant=tenant, is_active=True)
    measurement_points = PatMeasurementPoint.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "patronage/config_grading_rules.html",
        {
            "grading_rules": grading_rules,
            "size_charts": size_charts,
            "measurement_points": measurement_points,
            "error": error,
        },
    )
