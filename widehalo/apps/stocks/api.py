"""API django-ninja du module `stocks` (§5.8.6) — ST1 : entrepots
(`StkWarehouse`), emplacements (`StkLocation`), types de defaut
(`StkDefectType`). Montee sous `/api/v1/stocks` via `config/api.py`."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission
from apps.stocks.models import StkDefectType, StkLocation, StkWarehouse
from apps.stocks.services.defect_types import create_defect_type
from apps.stocks.services.warehouses import create_location, create_warehouse

router = Router(tags=["stocks"])


class WarehouseIn(Schema):
    code: str
    name: str
    type: str = StkWarehouse.TYPE_PRINCIPAL
    address: str = ""
    manager_id: str | None = None


class LocationIn(Schema):
    warehouse_id: str
    code: str
    name: str
    type: str = StkLocation.TYPE_INTERNE
    parent_id: str | None = None
    is_scrap: bool = False
    capacity: Decimal | None = None
    barcode: str = ""


class DefectTypeIn(Schema):
    code: str
    name: str
    category: str
    severity: str = StkDefectType.SEVERITY_MINEUR
    default_action: str = ""


def _serialize_warehouse(warehouse: StkWarehouse) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(warehouse.id),
        "code": warehouse.code,
        "name": warehouse.name,
        "type": warehouse.type,
        "address": warehouse.address,
        "manager_id": str(warehouse.manager_id) if warehouse.manager_id else None,
    }


def _serialize_location(location: StkLocation) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(location.id),
        "warehouse_id": str(location.warehouse_id),
        "code": location.code,
        "name": location.name,
        "type": location.type,
        "parent_id": str(location.parent_id) if location.parent_id else None,
        "is_scrap": location.is_scrap,
        "capacity": location.capacity,
        "barcode": location.barcode,
    }


def _serialize_defect_type(defect_type: StkDefectType) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(defect_type.id),
        "code": defect_type.code,
        "name": defect_type.name,
        "category": defect_type.category,
        "severity": defect_type.severity,
        "default_action": defect_type.default_action,
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# et `@require_permission(...)` l'INTERNE (juste au-dessus de `def`) — cf.
# `apps.core.services.permissions.require_permission` (bug T6, ne jamais
# inverser).


@router.get("/stocks/warehouses")
@require_permission("stocks.view_stkwarehouse")
def list_warehouses(request):
    warehouses = StkWarehouse.objects.all().order_by("-created_at")
    return {"results": [_serialize_warehouse(warehouse) for warehouse in warehouses]}


@router.post("/stocks/warehouses")
@require_permission("stocks.add_stkwarehouse")
def create_warehouse_endpoint(request, payload: WarehouseIn):
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    manager = get_object_or_404(User, id=payload.manager_id) if payload.manager_id else None
    warehouse = create_warehouse(
        tenant=tenant,
        code=payload.code,
        name=payload.name,
        type=payload.type,
        address=payload.address,
        manager=manager,
    )
    return _serialize_warehouse(warehouse)


@router.get("/stocks/locations")
@require_permission("stocks.view_stklocation")
def list_locations(request):
    locations = StkLocation.objects.all().order_by("-created_at")
    return {"results": [_serialize_location(location) for location in locations]}


@router.post("/stocks/locations")
@require_permission("stocks.add_stklocation")
def create_location_endpoint(request, payload: LocationIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    warehouse = get_object_or_404(StkWarehouse, id=payload.warehouse_id)
    parent = get_object_or_404(StkLocation, id=payload.parent_id) if payload.parent_id else None
    try:
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code=payload.code,
            name=payload.name,
            type=payload.type,
            parent=parent,
            is_scrap=payload.is_scrap,
            capacity=payload.capacity,
            barcode=payload.barcode,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_location(location)


@router.get("/stocks/defect-types")
@require_permission("stocks.view_stkdefecttype")
def list_defect_types(request):
    defect_types = StkDefectType.objects.all().order_by("-created_at")
    return {"results": [_serialize_defect_type(defect_type) for defect_type in defect_types]}


@router.post("/stocks/defect-types")
@require_permission("stocks.add_stkdefecttype")
def create_defect_type_endpoint(request, payload: DefectTypeIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    defect_type = create_defect_type(
        tenant=tenant,
        code=payload.code,
        name=payload.name,
        category=payload.category,
        severity=payload.severity,
        default_action=payload.default_action,
    )
    return _serialize_defect_type(defect_type)
