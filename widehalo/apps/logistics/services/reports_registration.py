"""§5.11 reporting, REP5 : enregistrement des rapports `logistics` deja
construits dans le registre partage `core.services.reports_registry`,
appele depuis `apps.py::ready()` — aucune reimplementation."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _current_tenant() -> Any:
    from apps.core.context import get_current_tenant_id
    from apps.core.models.tenant import Tenant

    tenant_id = get_current_tenant_id()
    assert tenant_id is not None  # noqa: S101 - deny-by-default deja garanti en amont (RLS/contexte)
    return Tenant.objects.get(id=tenant_id)


def _adapter_vehicle_cost_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.logistics.services.reports import vehicle_cost_rows

    return vehicle_cost_rows(_current_tenant())


def _adapter_shipment_status_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.logistics.services.reports import shipment_status_rows

    return shipment_status_rows(_current_tenant())


def _adapter_customs_duty_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.logistics.services.reports import customs_duty_rows

    return customs_duty_rows(_current_tenant())


def register_reports() -> None:
    register_report(
        code="LOG-VEH",
        module="logistics",
        label="Couts vehicules",
        permission="logistics.view_logvehicle",
        render_rows=_adapter_vehicle_cost_rows,
        fields=("vehicle_plate_number", "cost_type", "total_amount_mga", "entry_count"),
    )
    register_report(
        code="LOG-EXP",
        module="logistics",
        label="Expeditions",
        permission="logistics.view_logshipment",
        render_rows=_adapter_shipment_status_rows,
        fields=("reference", "origin", "destination", "state", "carrier_id", "freight_cost_mga"),
    )
    register_report(
        code="LOG-DOUANE",
        module="logistics",
        label="Droits de douane",
        permission="logistics.view_logcustomsfile",
        render_rows=_adapter_customs_duty_rows,
        fields=(
            "customs_file_reference",
            "hs_code",
            "description",
            "caf_value_mga",
            "duty_mga",
            "vat_mga",
            "landed_cost_mga",
        ),
    )
