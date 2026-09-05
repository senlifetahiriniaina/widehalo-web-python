"""API django-ninja du module `analytics` (§12) — authentifiée par jeton
JWT (`config.api.api`), même discipline que les autres modules (cf.
`apps.simulation.api`) : surface programmatique minimale pour ce lot
fondations, PAS la surface consommée par l'écran web (`apps.analytics.
views`), qui appelle directement `services/*`."""

from __future__ import annotations

from typing import Any

from ninja import Router, Schema

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import (
    available_facts,
    list_metrics_for_user,
    register_metric,
)
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


@router.get("/analytics/facts")
@require_permission("analytics.view_anmetricdefinition")
def list_facts_endpoint(request: Any) -> dict[str, Any]:
    """Faits de l'entrepot interrogeables et leurs axes (L8).

    Sans cet endpoint, un appelant programmatique ne peut pas savoir ce
    qu'il a le droit de declarer dans `fait_source`/`axes_autorises` : il
    devrait deviner, et `register_metric` le refuserait. Deriva de
    `fact_specs`, jamais d'une liste recopiee."""
    return {"results": available_facts()}


class MetricIn(Schema):
    code: str
    libelle: str
    module_source: str = ""
    description: str = ""
    formule: str = ""
    unite: str = ""
    fait_source: str = ""
    axes_autorises: list[str] = []
    roles_autorises: list[str] = []
    maille_minimale: str = ""
    statut: str = AnMetricDefinition.STATUT_BROUILLON


@router.post("/analytics/metrics")
@require_permission("analytics.change_anmetricdefinition")
def create_metric_endpoint(request: Any, payload: MetricIn) -> dict[str, Any]:
    """Cree un indicateur, ou en publie une nouvelle version (L8).

    `register_metric` versionne par INSERTION (BI-9) : un meme code
    renvoye avec des valeurs differentes cree une version n+1 et bascule
    `is_current`, il n'ecrase jamais la definition precedente — c'est
    exactement ce qu'un rapport deja genere doit pouvoir reconstituer.

    La validation du fait et des axes reste dans le service : la
    dupliquer ici creerait la seconde source de verite que ce lot supprime.
    Une `ValidationError` remonte en 400 par le gestionnaire global de
    `config.api`."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    metric = register_metric(
        tenant,
        code=payload.code,
        libelle=payload.libelle,
        module_source=payload.module_source,
        description=payload.description,
        formule=payload.formule,
        unite=payload.unite,
        fait_source=payload.fait_source,
        axes_autorises=payload.axes_autorises,
        roles_autorises=payload.roles_autorises,
        maille_minimale=payload.maille_minimale,
        statut=payload.statut,
        proprietaire=request.user,
    )
    return {
        "code": metric.code,
        "version": metric.version,
        "statut": metric.statut,
        "fait_source": metric.fait_source,
    }


@router.post("/analytics/warehouse/refresh")
@require_permission("analytics.add_anrefreshrun")
def refresh_warehouse_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    task_id = enqueue_refresh(tenant)
    return {"task_id": task_id}
