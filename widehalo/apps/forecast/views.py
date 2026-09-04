"""Écrans HTMX/session-authentifiés du module `forecast` (§13.2) —
`@login_required`, appel direct aux `services/*`, même patron que
`apps.bi.views`/`apps.simulation.views`.

**Deux gabarits** (budget écrans) : `forecast/index.html` (consolidée,
qualité, trésorerie, calendrier, publications, à onglets `?tab=`),
`forecast/workbench.html` (atelier de prévision pour UNE série :
diagnostic, courbe, ajustement — même patron que `simulation/
workbench.html`)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.core.views.tenant_web import resolve_tenant
from apps.forecast.models import ForExceptionalPoint, ForHoliday, ForPublication, ForSeriesForecast
from apps.forecast.services.adjustments import apply_adjustment, revert_adjustment
from apps.forecast.services.compute import compute_and_store_forecast
from apps.forecast.services.history import load_series_history
from apps.forecast.services.publication import publish
from apps.forecast.services.treasury import project_twelve_month_cash_inflows
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("forecast.view_forseriesforecast"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    tab = request.GET.get("tab", "consolidee")
    context = {"tab": tab, "can_manage": request.user.has_perm("forecast.add_forseriesforecast")}

    if tab == "qualite":
        context["forecasts"] = ForSeriesForecast.objects.filter(
            tenant=tenant, statistical_error_pct__isnull=False
        ).order_by("-period")[:50]
    elif tab == "tresorerie":
        context["projection"] = project_twelve_month_cash_inflows(tenant)
    elif tab == "calendrier":
        context["holidays"] = ForHoliday.objects.filter(tenant=tenant).order_by("date")
    elif tab == "publications":
        context["publications"] = ForPublication.objects.filter(tenant=tenant).order_by("-version")
    else:
        context["forecasts"] = ForSeriesForecast.objects.filter(tenant=tenant).order_by(
            "dimension_type", "dimension_value", "period"
        )[:100]
    return render(request, "forecast/index.html", context)


@login_required
def workbench(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("forecast.view_forseriesforecast"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    dimension_type = request.GET.get("dimension_type") or request.POST.get(
        "dimension_type", "canal"
    )
    dimension_value = request.GET.get("dimension_value") or request.POST.get(
        "dimension_value", "vente_directe"
    )
    error = ""

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "compute":
            if not request.user.has_perm("forecast.add_forseriesforecast"):
                return HttpResponse(status=403)
            compute_and_store_forecast(
                tenant, dimension_type=dimension_type, dimension_value=dimension_value
            )
        elif action in ("adjust", "revert"):
            if not request.user.has_perm("forecast.change_forseriesforecast"):
                return HttpResponse(status=403)
            forecast_id = request.POST.get("forecast_id")
            forecast = ForSeriesForecast.objects.filter(id=forecast_id).first()
            if forecast is not None:
                try:
                    if action == "adjust":
                        new_value = Decimal(request.POST.get("new_value", "0"))
                        apply_adjustment(
                            forecast,
                            new_value=new_value,
                            reason=request.POST.get("reason", ""),
                            user=request.user,
                        )
                    else:
                        revert_adjustment(
                            forecast, user=request.user, reason=request.POST.get("reason", "")
                        )
                except (ValidationError, InvalidOperation) as exc:
                    error = str(exc)
        elif action == "mark_exceptional":
            if not request.user.has_perm("forecast.add_forexceptionalpoint"):
                return HttpResponse(status=403)
            period_raw = request.POST.get("period")
            if period_raw:
                ForExceptionalPoint.objects.update_or_create(
                    tenant=tenant,
                    dimension_type=dimension_type,
                    dimension_value=dimension_value,
                    period=period_raw,
                    defaults={"reason": request.POST.get("reason", "")},
                )
        return redirect(
            f"/forecast/workbench/?dimension_type={dimension_type}&dimension_value={dimension_value}"
        )

    history = load_series_history(
        tenant, dimension_type=dimension_type, dimension_value=dimension_value
    )
    forecasts = ForSeriesForecast.objects.filter(
        tenant=tenant, dimension_type=dimension_type, dimension_value=dimension_value
    ).order_by("period")
    exceptional_periods = set(
        ForExceptionalPoint.objects.filter(
            tenant=tenant, dimension_type=dimension_type, dimension_value=dimension_value
        ).values_list("period", flat=True)
    )

    return render(
        request,
        "forecast/workbench.html",
        {
            "dimension_type": dimension_type,
            "dimension_value": dimension_value,
            "history": list(zip(history.full_periods, history.full_values, strict=True)),
            "excluded_periods": history.excluded_periods,
            "forecasts": forecasts,
            "exceptional_periods": exceptional_periods,
            "error": error,
            "can_manage": request.user.has_perm("forecast.add_forseriesforecast"),
        },
    )


@login_required
def publish_now(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("forecast.add_forpublication"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    publish(tenant, user=request.user)
    return redirect("/forecast/?tab=publications")
