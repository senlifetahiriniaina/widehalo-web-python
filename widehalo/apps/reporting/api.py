"""API django-ninja du module `reporting` (§5.11). Le catalogue (RPT-5) est
le seul endpoint de REP1 — generation (RPT-6, RPT-9), planification (RPT-7)
et archivage legal (RPT-10) arrivent aux etapes suivantes du meme
chantier."""

from __future__ import annotations

from ninja import Router

from apps.core.services.permissions import require_permission
from apps.core.services.reports_registry import list_registered_reports
from apps.core.tenant_context import activate_tenant
from apps.reporting.services.catalog import sync_report_definitions

router = Router(tags=["reporting"])


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
