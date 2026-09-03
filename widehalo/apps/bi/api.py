"""API django-ninja du module `bi` (§13.1) — authentifiée par jeton JWT
(`config.api.api`), même discipline que les autres modules : surface
programmatique minimale pour ce lot, PAS la surface consommée par les
écrans web (`apps.bi.views`), qui appellent directement `services/*`."""

from __future__ import annotations

from typing import Any

from ninja import Router

from apps.bi.models import BiReport
from apps.bi.services.query import run_report
from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission

router = Router(tags=["bi"])


@router.get("/bi/reports")
@require_permission("bi.view_bireport")
def list_reports_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    reports = BiReport.objects.filter(tenant=tenant, is_published=True)
    return {"results": [{"code": r.code, "name": r.name, "domaine": r.domaine} for r in reports]}


@router.get("/bi/reports/{code}/result")
@require_permission("bi.view_bireport")
def get_report_result_endpoint(request: Any, code: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    report = BiReport.objects.filter(tenant=tenant, code=code, is_published=True).first()
    if report is None:
        return {"detail": "not found"}
    return run_report(tenant, report, request.user)
