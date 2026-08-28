"""Rapports `logistics` (§5.7, LOG7 — dernier lot de `logistics`) : synthese
des couts vehicule, liste de statut des expeditions, synthese des droits de
douane.

`rows_to_bytes` est une COPIE volontaire du helper identique de
`apps.purchase.services.reports`/`apps.sales.services.reports`/
`apps.mrp.services.reports` (deja duplique par app dans ce projet, jamais
centralise dans `core`, verifie avant d'ecrire ce fichier) — suivre la
convention existante plutot que d'introduire une nouvelle dependance
inter-app pour un utilitaire generique."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.logistics.models import LogCustomsLine, LogShipment, LogVehicleCost


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


def vehicle_cost_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """Synthese des couts vehicule, une ligne par vehicule/type de cout —
    utilisee pour l'ecran de rapports (bouton de telechargement)."""
    costs = (
        LogVehicleCost.objects.filter(tenant=tenant, is_active=True)
        .select_related("vehicle")
        .order_by("vehicle__plate_number", "cost_type")
    )
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for cost in costs:
        key = (cost.vehicle.plate_number, cost.cost_type)
        entry = totals.setdefault(
            key,
            {
                "vehicle_plate_number": cost.vehicle.plate_number,
                "cost_type": cost.cost_type,
                "total_amount_mga": Decimal(0),
                "entry_count": 0,
            },
        )
        entry["total_amount_mga"] += cost.amount_mga
        entry["entry_count"] += 1
    return sorted(totals.values(), key=lambda row: (row["vehicle_plate_number"], row["cost_type"]))


def shipment_status_rows(tenant: Tenant) -> list[dict[str, Any]]:
    shipments = LogShipment.objects.filter(tenant=tenant, is_active=True).order_by("-created_at")
    return [
        {
            "reference": shipment.reference or str(shipment.id),
            "origin": shipment.origin,
            "destination": shipment.destination,
            "state": shipment.state,
            "carrier_id": str(shipment.carrier_id) if shipment.carrier_id else None,
            "freight_cost_mga": shipment.freight_cost_mga,
        }
        for shipment in shipments
    ]


def customs_duty_rows(tenant: Tenant) -> list[dict[str, Any]]:
    lines = (
        LogCustomsLine.objects.filter(tenant=tenant, is_active=True)
        .select_related("customs_file", "hs_code")
        .order_by("-created_at")
    )
    return [
        {
            "customs_file_reference": line.customs_file.reference or str(line.customs_file_id),
            "hs_code": line.hs_code.code,
            "description": line.description,
            "caf_value_mga": line.caf_value_mga,
            "duty_mga": line.duty_mga,
            "vat_mga": line.vat_mga,
            "landed_cost_mga": line.landed_cost_mga,
        }
        for line in lines
    ]
