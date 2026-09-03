"""API django-ninja du module `analytics` (§12) — authentifiée par jeton
JWT (`config.api.api`), même discipline que les autres modules (cf.
`apps.simulation.api`) : surface programmatique minimale pour ce lot
fondations, PAS la surface consommée par l'écran web (`apps.analytics.
views`), qui appelle directement `services/*`."""

from __future__ import annotations

from typing import Any

from ninja import Router

from apps.analytics.services.dictionary import list_metrics_for_user
from apps.analytics.services.refresh import enqueue_refresh
from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission

router = Router(tags=["analytics"])


@router.get("/analytics/metrics")
@require_permission("analytics.view_anmetricdefinition")
def list_metrics_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    metrics = list_metrics_for_user(tenant, request.user)
    return {
        "results": [
            {
                "code": metric.code,
                "libelle": metric.libelle,
                "unite": metric.unite,
                "module_source": metric.module_source,
                "axes_autorises": metric.axes_autorises,
                "maille_minimale": metric.maille_minimale,
            }
            for metric in metrics
        ]
    }


@router.post("/analytics/warehouse/refresh")
@require_permission("analytics.add_anrefreshrun")
def refresh_warehouse_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    task_id = enqueue_refresh(tenant)
    return {"task_id": task_id}
