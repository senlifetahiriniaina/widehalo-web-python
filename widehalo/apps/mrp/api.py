"""API django-ninja du module `mrp` (§5.3.7)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.mrp.models import (
    MrpBom,
    MrpCra,
    MrpOrder,
    MrpWorkOrder,
    MrpWorkshop,
)
from apps.mrp.services.bom import activate_bom, create_bom, explode, new_version
from apps.mrp.services.cra import reject_cra, submit_cra, validate_cra
from apps.mrp.services.orders import (
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    done_work_order,
    finish_order,
    pause_work_order,
    reserve_order,
    start_order,
    start_work_order,
)
from apps.mrp.services.reports import (
    cost_report,
    cra_summary,
    cri_summary,
    efficiency_report,
    order_pdf,
    rows_to_bytes,
    scrap_report,
    workload_report,
)

router = Router(tags=["mrp"])


class BomIn(Schema):
    code: str
    product_template_id: str
    uom_code: str = ""
    qty: Decimal = Decimal(1)


class OrderIn(Schema):
    bom_id: str
    workshop_id: str
    qty: Decimal


class CancelIn(Schema):
    reason: str


def _serialize_bom(bom: MrpBom) -> dict[str, Any]:
    return {"id": str(bom.id), "code": bom.code, "version": bom.version, "state": bom.state}


def _serialize_order(order: MrpOrder) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "reference": order.reference,
        "state": order.state,
        "qty": str(order.qty),
        "qty_produced": str(order.qty_produced),
    }


@router.get("/mrp/workshops")
def list_workshops(request):
    return {
        "results": [
            {"id": str(w.id), "code": w.code, "name": w.name} for w in MrpWorkshop.objects.all()
        ]
    }


@router.get("/mrp/boms")
def list_boms(request):
    return {"results": [_serialize_bom(b) for b in MrpBom.objects.all()]}


@router.post("/mrp/boms")
def create_bom_endpoint(request, payload: BomIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    bom = create_bom(
        tenant=tenant,
        code=payload.code,
        product_template_id=payload.product_template_id,
        qty=payload.qty,
        uom_code=payload.uom_code,
    )
    activate_bom(bom)
    return _serialize_bom(bom)


@router.post("/mrp/boms/{bom_id}/new-version")
def new_version_endpoint(request, bom_id: str):
    bom = get_object_or_404(MrpBom, id=bom_id)
    return _serialize_bom(new_version(bom))


@router.get("/mrp/boms/{bom_id}/explode")
def explode_endpoint(request, bom_id: str, qty: Decimal, size: str | None = None):
    bom = get_object_or_404(MrpBom, id=bom_id)
    rows = explode(bom, qty, size=size)
    return {
        "results": [
            {
                "component_template_id": str(r["component_template_id"]),
                "qty": str(r["qty"]),
            }
            for r in rows
        ]
    }


@router.get("/mrp/orders")
def list_orders(request):
    return {
        "results": [_serialize_order(o) for o in MrpOrder.objects.all().order_by("-created_at")]
    }


@router.post("/mrp/orders")
def create_order_endpoint(request, payload: OrderIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    bom = get_object_or_404(MrpBom, id=payload.bom_id)
    workshop = get_object_or_404(MrpWorkshop, id=payload.workshop_id)
    order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=payload.qty)
    return _serialize_order(order)


@router.post("/mrp/orders/{order_id}/confirm")
def confirm_order_endpoint(request, order_id: str):
    order = get_object_or_404(MrpOrder, id=order_id)
    try:
        confirm_order(order, request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.post("/mrp/orders/{order_id}/reserve")
def reserve_order_endpoint(request, order_id: str):
    order = get_object_or_404(MrpOrder, id=order_id)
    reserve_order(order, request.auth)
    return _serialize_order(order)


@router.post("/mrp/orders/{order_id}/start")
def start_order_endpoint(request, order_id: str):
    order = get_object_or_404(MrpOrder, id=order_id)
    start_order(order, request.auth)
    return _serialize_order(order)


@router.post("/mrp/orders/{order_id}/finish")
def finish_order_endpoint(
    request, order_id: str, qty_produced: Decimal, qty_scrapped: Decimal = Decimal(0)
):
    order = get_object_or_404(MrpOrder, id=order_id)
    finish_order(order, request.auth, qty_produced=qty_produced, qty_scrapped=qty_scrapped)
    return _serialize_order(order)


@router.post("/mrp/orders/{order_id}/close")
def close_order_endpoint(request, order_id: str):
    order = get_object_or_404(MrpOrder, id=order_id)
    close_order(order, request.auth)
    return _serialize_order(order)


@router.post("/mrp/orders/{order_id}/cancel")
def cancel_order_endpoint(request, order_id: str, payload: CancelIn):
    order = get_object_or_404(MrpOrder, id=order_id)
    try:
        cancel_order(order, request.auth, reason=payload.reason)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.post("/mrp/work-orders/{work_order_id}/start")
def start_work_order_endpoint(request, work_order_id: str):
    work_order = get_object_or_404(MrpWorkOrder, id=work_order_id)
    start_work_order(work_order, operator=request.auth)
    return {"id": str(work_order.id), "state": work_order.state}


@router.post("/mrp/work-orders/{work_order_id}/pause")
def pause_work_order_endpoint(request, work_order_id: str):
    work_order = get_object_or_404(MrpWorkOrder, id=work_order_id)
    pause_work_order(work_order)
    return {"id": str(work_order.id), "state": work_order.state}


@router.post("/mrp/work-orders/{work_order_id}/done")
def done_work_order_endpoint(
    request, work_order_id: str, qty_done: Decimal, qty_rejected: Decimal = Decimal(0)
):
    work_order = get_object_or_404(MrpWorkOrder, id=work_order_id)
    done_work_order(work_order, qty_done=qty_done, qty_rejected=qty_rejected)
    return {"id": str(work_order.id), "state": work_order.state}


@router.post("/mrp/cra/{cra_id}/submit")
def submit_cra_endpoint(request, cra_id: str):
    cra = get_object_or_404(MrpCra, id=cra_id)
    submit_cra(cra, request.auth)
    return {"id": str(cra.id), "state": cra.state}


@router.post("/mrp/cra/{cra_id}/validate")
def validate_cra_endpoint(request, cra_id: str):
    cra = get_object_or_404(MrpCra, id=cra_id)
    validate_cra(cra, request.auth)
    return {"id": str(cra.id), "state": cra.state}


@router.post("/mrp/cra/{cra_id}/reject")
def reject_cra_endpoint(request, cra_id: str):
    cra = get_object_or_404(MrpCra, id=cra_id)
    reject_cra(cra, request.auth)
    return {"id": str(cra.id), "state": cra.state}


@router.get("/mrp/reports/order/{order_id}.pdf")
def order_pdf_endpoint(request, order_id: str):
    order = get_object_or_404(MrpOrder, id=order_id)
    pdf_bytes = order_pdf(order)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{order.reference or order.id}.pdf"'
    return response


@router.get("/mrp/reports/cost/{order_id}")
def cost_report_endpoint(request, order_id: str):
    order = get_object_or_404(MrpOrder, id=order_id)
    return cost_report(order)


@router.get("/mrp/reports/cra")
def cra_report_endpoint(request, date_from: dt.date, date_to: dt.date, format: str = "json"):
    rows = cra_summary(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(
        rows, ["employee", "workshop", "state", "total_hours", "total_qty_done"], format=format
    )
    return _report_response(data, format)


@router.get("/mrp/reports/cri")
def cri_report_endpoint(request, date_from: dt.date, date_to: dt.date, format: str = "json"):
    rows = cri_summary(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(rows, ["workcenter", "type", "total_downtime_min", "count"], format=format)
    return _report_response(data, format)


@router.get("/mrp/reports/efficiency")
def efficiency_report_endpoint(request, workcenter_code: str | None = None, format: str = "json"):
    rows = efficiency_report(workcenter_code)
    data = rows_to_bytes(
        rows, ["workcenter", "qty_done", "qty_rejected", "efficiency_pct"], format=format
    )
    return _report_response(data, format)


@router.get("/mrp/reports/scrap")
def scrap_report_endpoint(request, date_from: dt.date, date_to: dt.date, format: str = "json"):
    rows = scrap_report(date_from=date_from, date_to=date_to)
    data = rows_to_bytes(rows, ["reason", "total_qty", "total_cost_mga"], format=format)
    return _report_response(data, format)


@router.get("/mrp/reports/workload/{workshop_id}")
def workload_report_endpoint(request, workshop_id: str, format: str = "json"):
    workshop = get_object_or_404(MrpWorkshop, id=workshop_id)
    rows = workload_report(workshop)
    data = rows_to_bytes(rows, ["workcenter", "total_planned_min"], format=format)
    return _report_response(data, format)


def _report_response(data: bytes, format: str) -> HttpResponse:
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return HttpResponse(data, content_type=content_type)
