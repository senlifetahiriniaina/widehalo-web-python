"""§5.11 reporting, REP5 : enregistrement des rapports `stocks` deja
construits dans le registre partage `core.services.reports_registry`,
appele depuis `apps.py::ready()` — aucune reimplementation. Ces rapports
n'etaient jusqu'ici exposes que par `apps.stocks.views_reports` (session
HTML) — les permissions choisies ici suivent le meme domaine que les
modeles concernes."""

from __future__ import annotations

import uuid
from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _current_tenant() -> Any:
    from apps.core.context import get_current_tenant_id
    from apps.core.models.tenant import Tenant

    tenant_id = get_current_tenant_id()
    assert tenant_id is not None  # noqa: S101 - deny-by-default deja garanti en amont (RLS/contexte)
    return Tenant.objects.get(id=tenant_id)


def _adapter_stock_state_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import stock_state_rows

    return stock_state_rows(_current_tenant())


def _adapter_move_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from django.utils.dateparse import parse_date

    from apps.stocks.services.reports import move_rows

    variant_raw = params.get("variant_id", "")
    return move_rows(
        _current_tenant(),
        date_from=parse_date(params.get("date_from", "")) if params.get("date_from") else None,
        date_to=parse_date(params.get("date_to", "")) if params.get("date_to") else None,
        variant_id=uuid.UUID(variant_raw) if variant_raw else None,
        move_type=params.get("move_type", ""),
    )


def _adapter_traceability_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.stocks.models import StkLot
    from apps.stocks.services.reports import traceability_rows

    lot = StkLot.objects.get(id=params["lot_id"])
    return traceability_rows(lot)


def _adapter_inventory_line_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.stocks.models import StkInventory
    from apps.stocks.services.reports import inventory_line_rows

    inventory = StkInventory.objects.get(id=params["inventory_id"])
    return inventory_line_rows(inventory)


def _adapter_defect_analysis_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import defect_analysis_rows

    return defect_analysis_rows(_current_tenant())


def _adapter_dormant_stock_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import dormant_stock_rows

    return dormant_stock_rows(_current_tenant())


def _adapter_production_consistency_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import production_consistency_rows

    return production_consistency_rows(_current_tenant())


def _adapter_measurement_variance_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import measurement_variance_rows

    return measurement_variance_rows(_current_tenant())


def _adapter_valuation_layer_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import valuation_layer_rows

    variant_raw = params.get("variant_id", "")
    return valuation_layer_rows(
        _current_tenant(), variant_id=uuid.UUID(variant_raw) if variant_raw else None
    )


def register_reports() -> None:
    register_report(
        code="STK-ETAT",
        module="stocks",
        label="Etat des stocks",
        permission="stocks.view_stkmove",
        render_rows=_adapter_stock_state_rows,
        fields=("location_id", "variant_id", "qty", "value_mga"),
    )
    register_report(
        code="STK-MOUV",
        module="stocks",
        label="Mouvements de stock",
        permission="stocks.view_stkmove",
        render_rows=_adapter_move_rows,
        fields=(
            "reference",
            "date",
            "move_type",
            "state",
            "variant_id",
            "lot_id",
            "qty",
            "uom",
            "location_from_id",
            "location_to_id",
            "unit_cost_mga",
            "value_mga",
            "source_document",
        ),
    )
    register_report(
        code="STK-TRAC",
        module="stocks",
        label="Tracabilite de lot",
        permission="stocks.view_stkmove",
        render_rows=_adapter_traceability_rows,
        fields=(
            "direction",
            "move_id",
            "reference",
            "date",
            "move_type",
            "qty",
            "location_from_id",
            "location_to_id",
            "source_document",
            "location_id",
            "qty_location",
        ),
    )
    register_report(
        code="STK-INV",
        module="stocks",
        label="Inventaire",
        permission="stocks.view_stkinventory",
        render_rows=_adapter_inventory_line_rows,
        fields=(
            "variant_id",
            "lot_id",
            "location_id",
            "qty_theoretical",
            "qty_counted",
            "difference",
            "reason",
        ),
    )
    register_report(
        code="STK-DEF",
        module="stocks",
        label="Analyse des defauts",
        permission="stocks.view_stkdefecttype",
        render_rows=_adapter_defect_analysis_rows,
        fields=("defect_type_code", "defect_type_name", "category", "state", "total_qty", "count"),
    )
    register_report(
        code="STK-AGE",
        module="stocks",
        label="Stock dormant",
        permission="stocks.view_stkmove",
        render_rows=_adapter_dormant_stock_rows,
        fields=(
            "variant_id",
            "location_id",
            "qty",
            "value_mga",
            "days_since_last_movement",
            "is_dormant",
        ),
    )
    register_report(
        code="STK-COHER",
        module="stocks",
        label="Coherence de production",
        permission="stocks.view_stkmove",
        render_rows=_adapter_production_consistency_rows,
        fields=(
            "order_id",
            "order_reference",
            "workshop_id",
            "qty_declared",
            "qty_entered_stock",
            "variance",
            "anomaly",
        ),
    )
    register_report(
        code="STK-MES",
        module="stocks",
        label="Ecarts de mesure",
        permission="stocks.view_stkmove",
        render_rows=_adapter_measurement_variance_rows,
        fields=("measured_at", "type", "value", "uom", "variance_pct", "device"),
    )
    register_report(
        code="STK-VAL",
        module="stocks",
        label="Valorisation des stocks",
        permission="stocks.view_stkmove",
        render_rows=_adapter_valuation_layer_rows,
        fields=(
            "variant_id",
            "date",
            "qty",
            "unit_cost_mga",
            "value_mga",
            "remaining_qty",
            "remaining_value_mga",
        ),
    )
