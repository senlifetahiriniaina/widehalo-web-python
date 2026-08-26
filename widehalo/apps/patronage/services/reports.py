"""Rapports patronage (§5.4.7) : PAT-TECH, PAT-MES, PAT-CONSO, PAT-MARKER,
PAT-VERS."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from apps.patronage.models import PatPattern
from apps.patronage.services.grading import apply_grading


def rows_to_bytes(rows: list[dict[str, Any]], fields: list[str], *, format: str = "json") -> bytes:
    if format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(field) for field in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format d'export non supporte : {format}")


def measurement_chart_report(pattern: PatPattern) -> list[dict[str, Any]]:
    """PAT-MES — tableau de mesures gradees, une ligne par point de mesure."""
    graded = apply_grading(pattern.size_chart)
    rows = []
    for code, values in graded.items():
        row: dict[str, Any] = {"measurement_point": code}
        row.update(values)
        rows.append(row)
    return rows


def consumption_report(pattern: PatPattern) -> list[dict[str, Any]]:
    """PAT-CONSO — consommation matiere par taille."""
    return [
        {
            "material_variant_id": str(c.material_variant_id),
            "size": c.size,
            "length_m": c.length_m,
            "waste_pct": c.waste_pct,
        }
        for c in pattern.consumptions.all()
    ]


def marker_report(pattern: PatPattern) -> list[dict[str, Any]]:
    """PAT-MARKER — plans de coupe calcules pour ce patron."""
    return [
        {
            "fabric_width_cm": m.fabric_width_cm,
            "size_ratio": m.size_ratio,
            "length_m": m.length_m,
            "efficiency_pct": m.efficiency_pct,
        }
        for m in pattern.markers.all()
    ]


def version_comparison_report(pattern: PatPattern) -> list[dict[str, Any]]:
    """PAT-VERS — comparatif des versions d'un meme patron (par code),
    en remontant la chaine `parent_pattern`."""
    versions = []
    current: PatPattern | None = pattern
    while current is not None:
        versions.append(
            {
                "version": current.version,
                "state": current.state,
                "pieces_count": current.pieces.count(),
                "date_created": current.date_created,
            }
        )
        current = current.parent_pattern
    return list(reversed(versions))
