"""API django-ninja du module `reporting` (§5.11). REP2 a ajoute la
generation (RPT-1/RPT-6/RPT-9) au catalogue (RPT-5) livre par REP1 — REP3
ajoute la planification (RPT-7). L'archivage legal (RPT-10) arrive a
l'etape suivante du meme chantier."""

from __future__ import annotations

import uuid
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema

from apps.core.models.user import User
from apps.core.services.permissions import require_permission
from apps.core.services.reports_registry import get_registered_report, list_registered_reports
from apps.core.tenant_context import activate_tenant
from apps.reporting.models import RptJob, RptSchedule
from apps.reporting.services.catalog import sync_report_definitions
from apps.reporting.services.engine import UnknownReportError, generate_report
from apps.reporting.services.scheduling import compute_next_run_at

router = Router(tags=["reporting"])


class GenerateReportIn(Schema):
    code: str
    params: dict[str, Any] = {}
    format: str = "json"
    lang: str = "fr"
    estimated_row_count: int | None = None


def _serialize_job(job: RptJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "report_code": job.report_code,
        "format": job.format,
        "state": job.state,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "download_url": f"/api/v1/reporting/jobs/{job.id}/download"
        if job.state == RptJob.STATE_DONE
        else None,
    }


@router.get("/reporting/catalog")
@require_permission("reporting.view_rptdefinition")
def catalog_endpoint(request):
    """RPT-5/RPT-11 : catalogue des rapports filtre par ce que l'utilisateur
    peut effectivement generer (permission propre au rapport, *pas*
    seulement `reporting.view_rptdefinition` qui ne garde que l'entree au
    module). Synchronise `RptDefinition` a la volee (idempotent, cf.
    `sync_report_definitions`) plutot que de dependre d'une commande
    d'administration lancee a part — un rapport nouvellement enregistre par
    un module (ex. apres deploiement) apparait donc immediatement."""
    # `TenantMiddleware` a deja active le contexte tenant courant pour cette
    # requete (RLS + `TenantManager`) ; `sync_report_definitions` a besoin de
    # l'objet `Tenant` lui-meme (FK), resolu depuis l'en-tete deja verifie
    # par le middleware.
    from apps.core.models.tenant import Tenant

    current_tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    with activate_tenant(current_tenant.id):
        sync_report_definitions(current_tenant)
    results = [
        {
            "code": report.code,
            "module": report.module,
            "label": report.label,
            "supports_pdf": report.supports_pdf(),
            "supports_rows": report.supports_rows(),
            "is_legal_document": report.is_legal_document,
        }
        for report in list_registered_reports()
        if request.auth.has_perm(report.permission)
    ]
    return {"results": results}


@router.post("/reporting/generate")
@require_permission("reporting.add_rptjob")
def generate_endpoint(request, payload: GenerateReportIn):
    """RPT-1/RPT-6/RPT-9 : genere (ou enfile) un rapport. La permission
    generique `reporting.add_rptjob` ouvre l'acces a l'action de generation
    elle-meme ; le rapport DEMANDE reste gate par SA PROPRE permission
    (`RegisteredReport.permission`) — un utilisateur qui a `reporting.
    add_rptjob` sans la permission du rapport cible recoit un 403, pas un
    rapport genere en douce."""
    report = get_registered_report(payload.code)
    if report is None:
        return JsonResponse({"detail": _("rapport inconnu")}, status=404)
    if not request.auth.has_perm(report.permission):
        return JsonResponse({"detail": _("permission refusée")}, status=403)

    tenant_id = request.headers.get("X-Tenant-Id")
    try:
        job = generate_report(
            code=payload.code,
            params=payload.params,
            format=payload.format,
            lang=payload.lang,
            actor=request.auth,
            tenant_id=tenant_id,
            estimated_row_count=payload.estimated_row_count,
        )
    except UnknownReportError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    return _serialize_job(job)


@router.get("/reporting/jobs/{job_id}")
@require_permission("reporting.view_rptjob")
def job_status_endpoint(request, job_id: str):
    job = get_object_or_404(RptJob, id=job_id)
    return _serialize_job(job)


@router.get("/reporting/jobs/{job_id}/download")
@require_permission("reporting.view_rptjob")
def job_download_endpoint(request, job_id: str):
    job = get_object_or_404(RptJob, id=job_id)
    if job.state != RptJob.STATE_DONE or not job.file:
        return JsonResponse({"detail": _("rapport pas encore disponible")}, status=409)
    content_types = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "json": "application/json",
    }
    response = HttpResponse(job.file.read(), content_type=content_types[job.format])
    response["Content-Disposition"] = f'attachment; filename="{job.report_code}.{job.format}"'
    return response


class ScheduleIn(Schema):
    name: str
    code: str
    params: dict[str, Any] = {}
    format: str = "json"
    lang: str = "fr"
    frequency: str
    recipient_ids: list[str] = []


def _serialize_schedule(schedule: RptSchedule) -> dict[str, Any]:
    return {
        "id": str(schedule.id),
        "name": schedule.name,
        "report_code": schedule.report_code,
        "frequency": schedule.frequency,
        "enabled": schedule.enabled,
        "next_run_at": schedule.next_run_at,
        "last_run_at": schedule.last_run_at,
        "recipients": [str(uid) for uid in schedule.recipients.values_list("id", flat=True)],
    }


@router.get("/reporting/schedules")
@require_permission("reporting.view_rptschedule")
def list_schedules_endpoint(request):
    tenant_id = request.headers.get("X-Tenant-Id")
    schedules = RptSchedule.objects.filter(tenant_id=tenant_id)
    return {"results": [_serialize_schedule(s) for s in schedules]}


@router.post("/reporting/schedules")
@require_permission("reporting.add_rptschedule")
def create_schedule_endpoint(request, payload: ScheduleIn):
    """RPT-7 : comme pour la generation immediate, la permission generique
    `reporting.add_rptschedule` ouvre l'action de planifier — le rapport
    CIBLE reste gate par sa propre permission."""
    report = get_registered_report(payload.code)
    if report is None:
        return JsonResponse({"detail": _("rapport inconnu")}, status=404)
    if not request.auth.has_perm(report.permission):
        return JsonResponse({"detail": _("permission refusée")}, status=403)
    if payload.frequency not in dict(RptSchedule.FREQUENCY_CHOICES):
        return JsonResponse({"detail": _("frequence de planification inconnue")}, status=400)

    tenant_id = request.headers.get("X-Tenant-Id")
    schedule = RptSchedule.objects.create(
        tenant_id=tenant_id,
        name=payload.name,
        report_code=payload.code,
        params=payload.params,
        format=payload.format,
        lang=payload.lang,
        frequency=payload.frequency,
        next_run_at=compute_next_run_at(payload.frequency),
        created_by=request.auth,
    )
    if payload.recipient_ids:
        recipients = User.objects.filter(id__in=[uuid.UUID(r) for r in payload.recipient_ids])
        schedule.recipients.set(recipients)
    return _serialize_schedule(schedule)


@router.post("/reporting/schedules/{schedule_id}/toggle")
@require_permission("reporting.change_rptschedule")
def toggle_schedule_endpoint(request, schedule_id: str):
    schedule = get_object_or_404(RptSchedule, id=schedule_id)
    schedule.enabled = not schedule.enabled
    schedule.save(update_fields=["enabled"])
    return _serialize_schedule(schedule)
