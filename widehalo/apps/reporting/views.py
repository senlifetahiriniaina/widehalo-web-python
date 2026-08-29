"""Ecrans HTMX/session du module `reporting` (§5.11, RPT-5/RPT-11). REP1 ne
livre que le catalogue en lecture — le formulaire de parametres/statut de
job (RPT-6) et la gestion des planifications (RPT-7) arrivent aux etapes
suivantes du meme chantier (REP6)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.services.reports_registry import list_registered_reports
from apps.core.tenant_context import activate_tenant
from apps.core.views.tenant_web import resolve_tenant
from apps.reporting.services.catalog import sync_report_definitions


@login_required
def catalog_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    with activate_tenant(tenant.id):
        sync_report_definitions(tenant)
    reports = [
        report for report in list_registered_reports() if request.user.has_perm(report.permission)
    ]
    return render(request, "reporting/catalog.html", {"reports": reports})
