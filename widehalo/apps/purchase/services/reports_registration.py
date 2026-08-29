"""§5.11 reporting, REP5 : enregistrement des rapports `purchase` deja
construits dans le registre partage `core.services.reports_registry`,
appele depuis `apps.py::ready()` — aucune reimplementation. Ces rapports
n'etaient jusqu'ici exposes que par `apps.purchase.views_reports`
(session HTML) — les permissions choisies ici suivent le meme domaine que
les modeles concernes, coherent avec `apps.core.services.rbac_policy.
ROLE_APP_PERMISSIONS["acheteur"]`."""

from __future__ import annotations

import uuid
from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_order_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.purchase.models import PurOrder
    from apps.purchase.services.reports import order_pdf

    order = PurOrder.objects.get(id=params["order_id"])
    return order_pdf(order)


def _adapter_rfq_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.purchase.models import PurRfq
    from apps.purchase.services.reports import rfq_rows

    rfq = PurRfq.objects.get(id=params["rfq_id"])
    return rfq_rows(rfq)


def _adapter_rfq_comparison_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.purchase.models import PurRfq
    from apps.purchase.services.reports import rfq_comparison_rows

    rfq = PurRfq.objects.get(id=params["rfq_id"])
    return rfq_comparison_rows(rfq)


def _adapter_reception_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.purchase.models import PurOrder
    from apps.purchase.services.reports import reception_rows

    order = PurOrder.objects.get(id=params["order_id"])
    return reception_rows(order)


def _current_tenant() -> Any:
    from apps.core.context import get_current_tenant_id
    from apps.core.models.tenant import Tenant

    tenant_id = get_current_tenant_id()
    assert tenant_id is not None  # noqa: S101 - deny-by-default deja garanti en amont (RLS/contexte)
    return Tenant.objects.get(id=tenant_id)


def _adapter_engagements_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.purchase.services.reports import engagements_rows

    return engagements_rows(_current_tenant())


def _adapter_supplier_evaluation_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.purchase.services.reports import supplier_evaluation_rows

    return supplier_evaluation_rows(uuid.UUID(params["partner_id"]))


def _adapter_late_orders_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.purchase.services.reports import late_orders_rows

    return late_orders_rows(_current_tenant())


def _adapter_cri_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.purchase.services.reports import cri_rows

    return cri_rows(_current_tenant(), state=params.get("state", ""), type=params.get("type", ""))


def register_reports() -> None:
    register_report(
        code="PUR-BC",
        module="purchase",
        label="Bon de commande",
        permission="purchase.view_purorder",
        render_pdf=_adapter_order_pdf,
    )
    register_report(
        code="PUR-RFQ",
        module="purchase",
        label="Appel d'offres",
        permission="purchase.view_purrfq",
        render_rows=_adapter_rfq_rows,
        fields=(
            "variant_id",
            "description",
            "qty",
            "uom",
            "suppliers_consulted",
            "responses_received",
        ),
    )
    register_report(
        code="PUR-COMP",
        module="purchase",
        label="Comparatif fournisseurs",
        permission="purchase.view_purrfq",
        render_rows=_adapter_rfq_comparison_rows,
        fields=(
            "response_id",
            "partner_id",
            "total_mga",
            "lead_time_days",
            "validity_date",
            "score",
        ),
    )
    register_report(
        code="PUR-REC",
        module="purchase",
        label="Reception",
        permission="purchase.view_purorder",
        render_rows=_adapter_reception_rows,
        fields=("date", "order_line_id", "description", "qty_received", "quality_status", "notes"),
    )
    register_report(
        code="PUR-ENG",
        module="purchase",
        label="Engagements d'achat",
        permission="purchase.view_purorder",
        render_rows=_adapter_engagements_rows,
        fields=("partner_id", "reference", "state", "amount_total_mga", "date_expected"),
    )
    register_report(
        code="PUR-EVAL",
        module="purchase",
        label="Evaluation fournisseurs",
        permission="purchase.view_purorder",
        render_rows=_adapter_supplier_evaluation_rows,
        fields=(
            "date",
            "score_quantity",
            "score_quality",
            "score_cost",
            "score_delay",
            "score_conformity",
            "weighted_score",
            "notes",
        ),
    )
    register_report(
        code="PUR-RET",
        module="purchase",
        label="Achats en retard",
        permission="purchase.view_purorder",
        render_rows=_adapter_late_orders_rows,
        fields=("reference", "partner_id", "date_expected", "state", "days_late"),
    )
    register_report(
        code="PUR-CRI",
        module="purchase",
        label="Incidents fournisseurs",
        permission="purchase.view_purcri",
        render_rows=_adapter_cri_rows,
        fields=(
            "reference",
            "date",
            "type",
            "partner_id",
            "order_reference",
            "description",
            "impact",
            "cost_mga",
            "state",
        ),
    )
