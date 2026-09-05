"""API django-ninja du module `forecast` (§13.2) — authentifiée par jeton
JWT, même discipline que les autres modules : surface programmatique
minimale, PAS la surface consommée par les écrans web (`apps.forecast.
views`), qui appellent directement `services/*`."""

from __future__ import annotations

from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission
from apps.forecast.models import ForSeriesForecast
from apps.forecast.services.compute import compute_and_store_forecast
from apps.forecast.services.material_needs import compute_material_needs
from ninja import Router

router = Router(tags=["forecast"])


@router.get("/forecast/series")
@require_permission("forecast.view_forseriesforecast")
def list_series_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rows = ForSeriesForecast.objects.filter(tenant=tenant).order_by(
        "dimension_type", "dimension_value", "period"
    )
    return {
        "results": [
            {
                "dimension_type": r.dimension_type,
                "dimension_value": r.dimension_value,
                "period": r.period,
                "selected_model": r.selected_model,
                "final_value": r.final_value,
                "error_mae_pct": r.error_mae_pct,
            }
            for r in rows
        ]
    }


@router.post("/forecast/series/compute")
@require_permission("forecast.add_forseriesforecast")
def compute_series_endpoint(
    request: Any, dimension_type: str, dimension_value: str
) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rows = compute_and_store_forecast(
        tenant, dimension_type=dimension_type, dimension_value=dimension_value
    )
    return {"computed": len(rows)}


@router.get("/forecast/material-needs")
@require_permission("forecast.view_forseriesforecast")
def material_needs_endpoint(request: Any, period_from: str, period_to: str) -> dict[str, Any]:
    """Bloc F, F1 : seul point d'entrée réel de `services.material_needs.
    compute_material_needs` — même permission que `list_series_endpoint`
    (aucun modèle dédié à « besoin matière », `direction`/
    `controleur_gestion` restent l'audience actuelle du module
    `forecast`, cf. `ROLE_APP_PERMISSIONS`)."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    needs = compute_material_needs(tenant, period_from=period_from, period_to=period_to)
    return {"results": needs}
