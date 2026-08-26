from __future__ import annotations

import csv
import io
import json
from typing import Any

from django.db.models import QuerySet

ASYNC_THRESHOLD = 5000


def export_queryset(queryset: QuerySet[Any], fields: list[str], *, format: str = "json") -> bytes:
    """Export synchrone d'un queryset — au-dela de ASYNC_THRESHOLD lignes,
    l'appelant doit deleguer a `core/tasks.py::enqueue()` (cf.
    services/export_async.py::enqueue_export) plutot qu'appeler cette
    fonction directement dans une requete web."""
    rows = list(queryset.values(*fields))

    if format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(f) for f in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format d'export non supporté : {format}")


def should_export_asynchronously(queryset: QuerySet[Any]) -> bool:
    return queryset.count() > ASYNC_THRESHOLD
