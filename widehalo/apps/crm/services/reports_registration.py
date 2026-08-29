"""§5.11 reporting, REP5 : enregistrement des rapports `crm` deja construits
dans le registre partage `core.services.reports_registry`, appele depuis
`apps.py::ready()` — aucune reimplementation, chaque adaptateur resout les
parametres puis appelle la fonction existante de `services/reports.py`."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_pipeline_breakdown(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.crm.models import CrmPipeline
    from apps.crm.services.reports import pipeline_breakdown

    pipeline = CrmPipeline.objects.get(id=params["pipeline_id"])
    return pipeline_breakdown(pipeline)


def _adapter_conversion_rate(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.crm.models import CrmPipeline
    from apps.crm.services.reports import conversion_rate

    pipeline = CrmPipeline.objects.get(id=params["pipeline_id"])
    # `conversion_rate` renvoie un dict agrege (pas une liste) — enveloppe
    # en une seule ligne, colonnes derivees dynamiquement par le moteur
    # (cf. `apps.reporting.services.engine.rows_to_bytes`, `fields=()`).
    return [conversion_rate(pipeline)]


def _adapter_activity_breakdown(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.crm.services.reports import activity_breakdown

    return activity_breakdown()


def _adapter_lost_reason_breakdown(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.crm.services.reports import lost_reason_breakdown

    return lost_reason_breakdown()


def register_reports() -> None:
    register_report(
        code="CRM-PIPE",
        module="crm",
        label="Repartition du pipeline",
        permission="crm.view_crmpipeline",
        render_rows=_adapter_pipeline_breakdown,
        fields=("stage_code", "stage_name", "lead_count", "total_expected_revenue_mga"),
    )
    register_report(
        code="CRM-CONV",
        module="crm",
        label="Taux de conversion",
        permission="crm.view_crmpipeline",
        render_rows=_adapter_conversion_rate,
    )
    register_report(
        code="CRM-ACT",
        module="crm",
        label="Activites par type",
        permission="crm.view_crmactivity",
        render_rows=_adapter_activity_breakdown,
        fields=("activity_type", "count"),
    )
    register_report(
        code="CRM-PERTE",
        module="crm",
        label="Motifs de perte",
        # crm.view_crmlead (pas crm.view_crmlostreason) : le rapport agrege
        # des donnees de leads, meme choix documente que
        # `apps.crm.api::lost_report_endpoint`.
        permission="crm.view_crmlead",
        render_rows=_adapter_lost_reason_breakdown,
        fields=("lost_reason", "lead_count", "total_expected_revenue_mga"),
    )
