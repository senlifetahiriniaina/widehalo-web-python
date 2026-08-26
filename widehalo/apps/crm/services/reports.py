"""Rapports CRM (§5.2.8) : CRM-PIPE (repartition du pipeline par etape),
CRM-CONV (taux de conversion gagne/perdu), CRM-ACT (activites par type),
CRM-LOST (motifs de perte). CRM-DEVIS/CRM-PROF sont hors perimetre (cf.
plan, dependent de `sales`)."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum

from apps.crm.models import CrmActivity, CrmLead, CrmPipeline


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


def pipeline_breakdown(pipeline: CrmPipeline) -> list[dict[str, Any]]:
    """CRM-PIPE : nombre d'opportunites et revenu attendu cumule par etape."""
    rows = (
        CrmLead.objects.filter(pipeline=pipeline)
        .values("stage__code", "stage__name", "stage__sequence")
        .annotate(lead_count=Count("id"), total_expected_revenue=Sum("expected_revenue_mga"))
        .order_by("stage__sequence")
    )
    return [
        {
            "stage_code": row["stage__code"],
            "stage_name": row["stage__name"],
            "lead_count": row["lead_count"],
            "total_expected_revenue_mga": row["total_expected_revenue"] or Decimal(0),
        }
        for row in rows
    ]


def conversion_rate(pipeline: CrmPipeline) -> dict[str, Any]:
    """CRM-CONV : taux de conversion sur les opportunites cloturees
    (gagnees / (gagnees + perdues)), 0 si aucune opportunite cloturee."""
    leads = CrmLead.objects.filter(pipeline=pipeline)
    won = leads.filter(won_at__isnull=False).count()
    lost = leads.filter(lost_at__isnull=False).count()
    closed = won + lost
    rate = Decimal(won) / Decimal(closed) * 100 if closed else Decimal(0)
    return {"won": won, "lost": lost, "closed": closed, "conversion_rate_pct": rate}


def activity_breakdown(lead: CrmLead | None = None) -> list[dict[str, Any]]:
    """CRM-ACT : nombre d'activites par type, optionnellement restreint a
    une opportunite."""
    queryset = CrmActivity.objects.all()
    if lead is not None:
        queryset = queryset.filter(lead=lead)
    rows = queryset.values("activity_type").annotate(count=Count("id")).order_by("-count")
    return [{"activity_type": row["activity_type"], "count": row["count"]} for row in rows]


def lost_reason_breakdown() -> list[dict[str, Any]]:
    """CRM-LOST : nombre d'opportunites perdues et revenu attendu perdu,
    par motif de perte."""
    rows = (
        CrmLead.objects.filter(lost_at__isnull=False)
        .values("lost_reason__name")
        .annotate(lead_count=Count("id"), total_expected_revenue=Sum("expected_revenue_mga"))
        .order_by("-lead_count")
    )
    return [
        {
            "lost_reason": row["lost_reason__name"] or "(non renseigne)",
            "lead_count": row["lead_count"],
            "total_expected_revenue_mga": row["total_expected_revenue"] or Decimal(0),
        }
        for row in rows
    ]
