"""Ecran de configuration du module `sales` (S7), regroupe sous le hub
"Parametres" (meme convention que `apps.mrp.views_config`) : gabarits de
recurrence (`SalesRecurrence`, RG-SAL-6). Liste+creation combinees dans un
seul ecran (meme patron que `mrp/config_workshops.html`) — pas de detail
dedie, un gabarit de recurrence n'a pas d'etat/de sous-entites a gerer une
fois cree.

Perimetre assume et documente (§5.5.7, S7) : `SalesCustomerCalendar`/
`SalesTarget`/`SalesForecast` (S6) n'ont PAS d'ecran de configuration/CRUD
dedie dans ce lot — seul `SalesForecast` a un ecran de lecture (SAL-PREV,
cf. `apps.sales.views_reports.report_forecast`). Deferre explicitement,
pas silencieusement omis : construire 3 ecrans de configuration
supplementaires pour des entites recentes (S6) sans retour utilisateur sur
leur usage reel aurait gonfle le budget d'ecrans (plafond CDC 90) pour un
gain incertain — a construire des qu'un besoin concret est exprime."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from apps.core.views.tenant_web import resolve_tenant
from apps.sales.models import SalesOrder, SalesRecurrence
from apps.sales.services.recurrence import create_recurrence


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def config_recurrences(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            template_order = get_object_or_404(SalesOrder, id=request.POST.get("template_order_id"))
            start_date = parse_date(request.POST.get("start_date", ""))
            if start_date is None:
                raise ValidationError("La date de debut est obligatoire.")
            create_recurrence(
                tenant=tenant,
                name=request.POST.get("name", ""),
                interval=request.POST.get("interval", SalesRecurrence.INTERVAL_MONTHLY),
                start_date=start_date,
                template_order=template_order,
                day_rule=request.POST.get("day_rule", ""),
                end_date=parse_date(request.POST.get("end_date", "")),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:config_recurrences")

    recurrences = SalesRecurrence.objects.filter(tenant=tenant, is_active=True)
    templates = SalesOrder.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "sales/config_recurrences.html",
        {"recurrences": recurrences, "templates": templates, "error": error},
    )
