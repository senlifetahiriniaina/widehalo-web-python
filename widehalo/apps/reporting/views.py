"""Ecrans HTMX/session du module `reporting` (§5.11). REP1 a livre le
catalogue en lecture ; REP6 ajoute le formulaire de generation + statut de
job (RPT-6) et la gestion des planifications (RPT-7)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from apps.core.services.reports_registry import get_registered_report, list_registered_reports
from apps.core.tenant_context import activate_tenant
from apps.core.views.tenant_web import resolve_tenant
from apps.reporting.models import RptJob, RptSchedule
from apps.reporting.services.catalog import sync_report_definitions
from apps.reporting.services.engine import UnknownReportError, generate_report
from apps.reporting.services.scheduling import compute_next_run_at


@login_required
def catalog_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    with activate_tenant(tenant.id):
        sync_report_definitions(tenant)
    reports = [
        report for report in list_registered_reports() if request.user.has_perm(report.permission)
    ]
    return render(request, "reporting/catalog.html", {"reports": reports})


@login_required
def generate_form(request: HttpRequest, code: str) -> HttpResponse:
    """RPT-6 : formulaire de generation (parametres JSON libres, format) —
    volontairement minimal (un `<textarea>` JSON plutot qu'un formulaire
    dynamique par rapport, qui exigerait un schema de parametres par
    rapport hors perimetre de ce chantier, cf. RPT-12 explicitement [V2])."""
    report = get_registered_report(code)
    if report is None or not request.user.has_perm(report.permission):
        return HttpResponse(status=404)
    return render(request, "reporting/generate.html", {"code": code, "report": report})


@login_required
def generate_submit(request: HttpRequest, code: str) -> HttpResponse:
    import json

    tenant = resolve_tenant(request)
    report = get_registered_report(code)
    if report is None or not request.user.has_perm(report.permission):
        return HttpResponse(status=403)

    params_raw = request.POST.get("params", "").strip()
    params = json.loads(params_raw) if params_raw else {}
    format = request.POST.get("format", "json")

    with activate_tenant(tenant.id):
        try:
            job = generate_report(
                code=code,
                params=params,
                format=format,
                lang=request.user.preferred_language,
                actor=request.user,
                tenant_id=str(tenant.id),
            )
        except UnknownReportError:
            return HttpResponse(status=404)
    return render(request, "reporting/_job_status.html", {"job": job})


@login_required
def job_status(request: HttpRequest, job_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    with activate_tenant(tenant.id):
        job = get_object_or_404(RptJob, id=job_id)
    return render(request, "reporting/_job_status.html", {"job": job})


@login_required
def schedules_index(request: HttpRequest) -> HttpResponse:
    """RPT-7 : liste + creation de planifications."""
    tenant = resolve_tenant(request)
    if not request.user.has_perm("reporting.view_rptschedule"):
        return HttpResponse(status=403)

    if request.method == "POST":
        if not request.user.has_perm("reporting.add_rptschedule"):
            return HttpResponse(status=403)
        code = request.POST.get("code", "")
        report = get_registered_report(code)
        if report is None or not request.user.has_perm(report.permission):
            return JsonResponse({"detail": _("rapport inconnu ou non autorise")}, status=404)
        with activate_tenant(tenant.id):
            RptSchedule.objects.create(
                tenant=tenant,
                name=request.POST.get("name", code),
                report_code=code,
                format=request.POST.get("format", "json"),
                frequency=request.POST.get("frequency", RptSchedule.FREQUENCY_WEEKLY),
                next_run_at=compute_next_run_at(
                    request.POST.get("frequency", RptSchedule.FREQUENCY_WEEKLY)
                ),
                created_by=request.user,
            )

    with activate_tenant(tenant.id):
        schedules = RptSchedule.objects.all()
        reports = [r for r in list_registered_reports() if request.user.has_perm(r.permission)]
    return render(request, "reporting/schedules.html", {"schedules": schedules, "reports": reports})


@login_required
def schedule_toggle(request: HttpRequest, schedule_id: str) -> HttpResponse:
    if not request.user.has_perm("reporting.change_rptschedule"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    with activate_tenant(tenant.id):
        schedule = get_object_or_404(RptSchedule, id=schedule_id)
        schedule.enabled = not schedule.enabled
        schedule.save(update_fields=["enabled"])
    return render(request, "reporting/_schedule_row.html", {"schedule": schedule})
