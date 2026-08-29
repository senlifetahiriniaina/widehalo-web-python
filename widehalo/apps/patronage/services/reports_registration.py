"""§5.11 reporting, REP5 : enregistrement des rapports `patronage` deja
construits dans le registre partage `core.services.reports_registry`,
appele depuis `apps.py::ready()` — aucune reimplementation."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_measurement_chart_report(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.patronage.models import PatPattern
    from apps.patronage.services.reports import measurement_chart_report

    pattern = PatPattern.objects.get(id=params["pattern_id"])
    return measurement_chart_report(pattern)


def _adapter_consumption_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.patronage.models import PatPattern
    from apps.patronage.services.reports import consumption_report

    pattern = PatPattern.objects.get(id=params["pattern_id"])
    return consumption_report(pattern)


def _adapter_marker_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.patronage.models import PatPattern
    from apps.patronage.services.reports import marker_report

    pattern = PatPattern.objects.get(id=params["pattern_id"])
    return marker_report(pattern)


def _adapter_version_comparison_report(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.patronage.models import PatPattern
    from apps.patronage.services.reports import version_comparison_report

    pattern = PatPattern.objects.get(id=params["pattern_id"])
    return version_comparison_report(pattern)


def register_reports() -> None:
    register_report(
        code="PAT-MES",
        module="patronage",
        label="Tableau de mesures",
        permission="patronage.view_patsizechart",
        render_rows=_adapter_measurement_chart_report,
        # Colonnes dependantes de `pattern.size_chart.sizes` (variable par
        # patron) — derivees dynamiquement par le moteur (`fields=()`).
    )
    register_report(
        code="PAT-CONSO",
        module="patronage",
        label="Consommation matiere",
        permission="patronage.view_patconsumption",
        render_rows=_adapter_consumption_report,
        fields=("material_variant_id", "size", "length_m", "waste_pct"),
    )
    register_report(
        code="PAT-MARKER",
        module="patronage",
        label="Plan de coupe",
        permission="patronage.view_patmarker",
        render_rows=_adapter_marker_report,
        fields=("fabric_width_cm", "size_ratio", "length_m", "efficiency_pct"),
    )
    register_report(
        code="PAT-VERS",
        module="patronage",
        label="Comparaison de versions",
        permission="patronage.view_patpattern",
        render_rows=_adapter_version_comparison_report,
        fields=("version", "state", "pieces_count", "date_created"),
    )
