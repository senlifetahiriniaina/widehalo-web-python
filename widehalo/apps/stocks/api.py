"""API django-ninja du module `stocks` (§5.8.6). ST1 : entrepots
(`StkWarehouse`), emplacements (`StkLocation`), types de defaut
(`StkDefectType`). ST8 (cf. plan) : quants, mouvements (+validation/
annulation), pickings (+validation), mesures, etats qualite, inventaires
(+validation), tracabilite, disponibilite, rapport de coherence — §5.8.6
liste ces endpoints litteralement. Montee sous `/api/v1/stocks` via
`config/api.py`.

**Endpoints de transition non listes explicitement par le CDC (moves
validate/cancel, pickings ready/validate)** : ajoutes par symetrie avec
CHAQUE autre entite porteuse d'un cycle de vie de ce depot
(`PurOrder`/`SalesOrder`/`MrpOrder`...), qui expose systematiquement ses
transitions via l'API — meme discipline documentee explicitement par la
consigne de ce lot ("la liste du CDC ne montre pas d'action
valider/annuler explicite, mirroir la convention" ST8)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.files import UploadedFile

from apps.core.services.permissions import require_permission
from apps.stocks.models import (
    StkDefectType,
    StkImportRow,
    StkInventory,
    StkLocation,
    StkLot,
    StkMove,
    StkPicking,
    StkQuant,
    StkWarehouse,
)
from apps.stocks.services.consistency import (
    production_consistency_report,
    quant_ledger_consistency_report,
)
from apps.stocks.services.defect_types import create_defect_type
from apps.stocks.services.inventory import (
    add_inventory_line,
    create_inventory,
    validate_inventory,
)
from apps.stocks.services.measurements import record_measurement
from apps.stocks.services.moves import (
    cancel_move,
    create_move,
    receive_warehouse_transfer,
    transfer_between_warehouses,
    validate_move,
)
from apps.stocks.services.pickings import (
    add_picking_line,
    create_picking,
    mark_picking_ready,
    validate_picking,
)
from apps.stocks.services.quality import set_quality_state
from apps.stocks.services.quants import available_qty, on_hand_qty
from apps.stocks.services.stock_import import (
    import_stock_quantities_xlsx,
)
from apps.stocks.services.stock_import import (
    qualify_import_row as qualify_stock_import_row,
)
from apps.stocks.services.stock_import import (
    resolve_import_row as resolve_stock_import_row,
)
from apps.stocks.services.traceability import lot_traceability
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


# ---------------------------------------------------------------------------
# ST8 (§5.8.6) : quants, mouvements, pickings, mesures, etats qualite,
# inventaires, tracabilite, disponibilite, rapport de coherence.
# ---------------------------------------------------------------------------


class MoveIn(Schema):
    variant_id: str
    qty: Decimal
    uom: str = ""
    location_from_id: str
    location_to_id: str
    date: str
    move_type: str
    source_document: str = ""
    unit_cost_mga: Decimal = Decimal(0)
    lot_id: str | None = None


class TransferIn(Schema):
    variant_id: str
    qty: Decimal
    uom: str = ""
    source_warehouse_id: str
    destination_warehouse_id: str
    date: str
    source_document: str = ""
    unit_cost_mga: Decimal = Decimal(0)
    lot_id: str | None = None


class ReceiveTransferIn(Schema):
    date: str
    qty: Decimal | None = None


class PickingIn(Schema):
    type: str
    location_from_id: str
    location_to_id: str
    partner_id: str | None = None
    date_scheduled: str | None = None
    source_document: str = ""
    carrier: str = ""
    tracking: str = ""


class PickingLineIn(Schema):
    variant_id: str
    qty: Decimal
    uom: str = ""
    unit_cost_mga: Decimal = Decimal(0)
    lot_id: str | None = None


class MeasurementIn(Schema):
    type: str
    value: Decimal
    uom: str = ""
    theoretical_value: Decimal | None = None
    device: str = ""
    partner_id_for_dispute: str | None = None


class QualityStateIn(Schema):
    quant_id: str | None = None
    lot_id: str | None = None
    state: str
    defect_type_id: str | None = None
    defect_qty: Decimal = Decimal(0)
    description: str = ""


class InventoryIn(Schema):
    warehouse_id: str
    date: str
    type: str = StkInventory.TYPE_PONCTUEL


class InventoryLineIn(Schema):
    variant_id: str
    location_id: str
    lot_id: str | None = None


def _serialize_move(move: StkMove) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(move.id),
        "reference": move.reference,
        "variant_id": str(move.variant_id),
        "lot_id": str(move.lot_id) if move.lot_id else None,
        "qty": move.qty,
        "uom": move.uom,
        "location_from_id": str(move.location_from_id),
        "location_to_id": str(move.location_to_id),
        "date": move.date,
        "state": move.state,
        "move_type": move.move_type,
        "source_document": move.source_document,
        "unit_cost_mga": move.unit_cost_mga,
        "value_mga": move.value_mga,
    }


def _serialize_picking(picking: StkPicking) -> dict:  # type: ignore[type-arg]
    return {
        "id": str(picking.id),
        "reference": picking.reference,
        "type": picking.type,
        "state": picking.state,
        "location_from_id": str(picking.location_from_id),
        "location_to_id": str(picking.location_to_id),
        "partner_id": str(picking.partner_id) if picking.partner_id else None,
    }


def _tenant(request):  # type: ignore[no-untyped-def]
    from apps.core.models.tenant import Tenant

    return Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))


@router.get("/stocks/quants")
@require_permission("stocks.view_stkquant")
def list_quants(
    request, variant: str | None = None, location: str | None = None, lot: str | None = None
):  # noqa: E501
    quants = StkQuant.objects.all()
    if variant:
        quants = quants.filter(variant_id=variant)
    if location:
        quants = quants.filter(location_id=location)
    if lot:
        quants = quants.filter(lot_id=lot)
    return {
        "results": [
            {
                "id": str(quant.id),
                "variant_id": str(quant.variant_id),
                "location_id": str(quant.location_id),
                "lot_id": str(quant.lot_id) if quant.lot_id else None,
                "qty": quant.qty,
                "qty_reserved": quant.qty_reserved,
                "unit_cost_mga": quant.unit_cost_mga,
                "value_mga": quant.value_mga,
            }
            for quant in quants
        ]
    }


@router.get("/stocks/moves")
@require_permission("stocks.view_stkmove")
def list_moves(request):
    moves = StkMove.objects.all().order_by("-date", "-created_at")
    return {"results": [_serialize_move(move) for move in moves]}


@router.post("/stocks/moves")
@require_permission("stocks.add_stkmove")
def create_move_endpoint(request, payload: MoveIn):
    tenant = _tenant(request)
    lot = get_object_or_404(StkLot, id=payload.lot_id) if payload.lot_id else None
    try:
        move = create_move(
            tenant=tenant,
            variant_id=uuid.UUID(payload.variant_id),
            qty=payload.qty,
            uom=payload.uom,
            location_from=get_object_or_404(StkLocation, id=payload.location_from_id),
            location_to=get_object_or_404(StkLocation, id=payload.location_to_id),
            date=dt.date.fromisoformat(payload.date),
            move_type=payload.move_type,
            source_document=payload.source_document,
            unit_cost_mga=payload.unit_cost_mga,
            lot=lot,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(move)


@router.post("/stocks/moves/{move_id}/validate")
@require_permission("stocks.change_stkmove")
def validate_move_endpoint(request, move_id: str):
    move = get_object_or_404(StkMove, id=move_id)
    try:
        validate_move(move)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(move)


@router.post("/stocks/moves/{move_id}/cancel")
@require_permission("stocks.change_stkmove")
def cancel_move_endpoint(request, move_id: str, reason: str = ""):
    move = get_object_or_404(StkMove, id=move_id)
    try:
        cancel_move(move, reason=reason)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(move)


@router.post("/stocks/transfers")
@require_permission("stocks.add_stkmove")
def transfer_between_warehouses_endpoint(request, payload: TransferIn):
    """STK-5 (Phase 3 §5.8, sprint A1) : départ d'un transfert entre deux
    entrepôts distincts (phase 1 — cf. `services.moves.
    transfer_between_warehouses`). La marchandise passe par un emplacement
    de transit ; `receive_transfer_endpoint` ci-dessous clôture le
    transfert à l'arrivée réelle (phase 2)."""
    tenant = _tenant(request)
    lot = get_object_or_404(StkLot, id=payload.lot_id) if payload.lot_id else None
    try:
        move = transfer_between_warehouses(
            tenant=tenant,
            variant_id=uuid.UUID(payload.variant_id),
            qty=payload.qty,
            uom=payload.uom,
            source_warehouse=get_object_or_404(StkWarehouse, id=payload.source_warehouse_id),
            destination_warehouse=get_object_or_404(
                StkWarehouse, id=payload.destination_warehouse_id
            ),
            date=dt.date.fromisoformat(payload.date),
            source_document=payload.source_document,
            unit_cost_mga=payload.unit_cost_mga,
            lot=lot,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(move)


@router.post("/stocks/transfers/{move_id}/receive")
@require_permission("stocks.add_stkmove")
def receive_transfer_endpoint(request, move_id: str, payload: ReceiveTransferIn):
    """STK-5 : arrivée réelle d'un transfert entre entrepôts démarré via
    `transfer_between_warehouses_endpoint` ci-dessus (phase 2 — cf.
    `services.moves.receive_warehouse_transfer`). `move_id` est le
    mouvement de DÉPART (destination = emplacement de transit)."""
    transit_move = get_object_or_404(StkMove, id=move_id)
    try:
        move = receive_warehouse_transfer(
            transit_move,
            date=dt.date.fromisoformat(payload.date),
            qty=payload.qty,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(move)


@router.get("/stocks/quant-consistency-report")
@require_permission("stocks.view_stkmove")
def quant_consistency_report_endpoint(request):
    """STK-2 (Phase 3 §5.8, sprint A1) : écran/API de contrôle de
    divergence entre `StkQuant` (matérialisé) et l'agrégat des `StkMove`
    (source de vérité) — cf. `services.consistency.
    quant_ledger_consistency_report`."""
    tenant = _tenant(request)
    rows = quant_ledger_consistency_report(tenant)
    return {
        "results": [
            {
                "quant_id": str(row["quant_id"]),
                "variant_id": str(row["variant_id"]),
                "location_id": str(row["location_id"]),
                "lot_id": str(row["lot_id"]) if row["lot_id"] else None,
                "recorded_qty": row["recorded_qty"],
                "derived_qty": row["derived_qty"],
                "variance": row["variance"],
                "anomaly": row["anomaly"],
            }
            for row in rows
        ]
    }


@router.get("/stocks/pickings")
@require_permission("stocks.view_stkpicking")
def list_pickings(request):
    pickings = StkPicking.objects.all().order_by("-created_at")
    return {"results": [_serialize_picking(picking) for picking in pickings]}


@router.post("/stocks/pickings")
@require_permission("stocks.add_stkpicking")
def create_picking_endpoint(request, payload: PickingIn):
    tenant = _tenant(request)
    try:
        picking = create_picking(
            tenant=tenant,
            type=payload.type,
            location_from=get_object_or_404(StkLocation, id=payload.location_from_id),
            location_to=get_object_or_404(StkLocation, id=payload.location_to_id),
            partner_id=uuid.UUID(payload.partner_id) if payload.partner_id else None,
            date_scheduled=dt.date.fromisoformat(payload.date_scheduled)
            if payload.date_scheduled
            else None,
            source_document=payload.source_document,
            carrier=payload.carrier,
            tracking=payload.tracking,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_picking(picking)


@router.post("/stocks/pickings/{picking_id}/lines")
@require_permission("stocks.change_stkpicking")
def add_picking_line_endpoint(request, picking_id: str, payload: PickingLineIn):
    picking = get_object_or_404(StkPicking, id=picking_id)
    lot = get_object_or_404(StkLot, id=payload.lot_id) if payload.lot_id else None
    try:
        add_picking_line(
            picking,
            variant_id=uuid.UUID(payload.variant_id),
            qty=payload.qty,
            uom=payload.uom,
            unit_cost_mga=payload.unit_cost_mga,
            lot=lot,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_picking(picking)


@router.post("/stocks/pickings/{picking_id}/ready")
@require_permission("stocks.change_stkpicking")
def picking_ready_endpoint(request, picking_id: str):
    picking = get_object_or_404(StkPicking, id=picking_id)
    try:
        mark_picking_ready(picking)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_picking(picking)


@router.post("/stocks/pickings/{picking_id}/validate")
@require_permission("stocks.change_stkpicking")
def picking_validate_endpoint(request, picking_id: str):
    picking = get_object_or_404(StkPicking, id=picking_id)
    try:
        validate_picking(picking)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_picking(picking)


@router.post("/stocks/measurements")
@require_permission("stocks.add_stkmeasurement")
def create_measurement_endpoint(request, payload: MeasurementIn):
    tenant = _tenant(request)
    try:
        measurement = record_measurement(
            tenant=tenant,
            type=payload.type,
            value=payload.value,
            uom=payload.uom,
            theoretical_value=payload.theoretical_value,
            device=payload.device,
            partner_id_for_dispute=uuid.UUID(payload.partner_id_for_dispute)
            if payload.partner_id_for_dispute
            else None,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {
        "id": str(measurement.id),
        "type": measurement.type,
        "value": measurement.value,
        "variance_pct": measurement.variance_pct,
    }


@router.post("/stocks/quality-states")
@require_permission("stocks.add_stkqualitystate")
def create_quality_state_endpoint(request, payload: QualityStateIn):
    tenant = _tenant(request)
    quant = get_object_or_404(StkQuant, id=payload.quant_id) if payload.quant_id else None
    lot = get_object_or_404(StkLot, id=payload.lot_id) if payload.lot_id else None
    defect_type = (
        get_object_or_404(StkDefectType, id=payload.defect_type_id)
        if payload.defect_type_id
        else None
    )
    try:
        quality_state = set_quality_state(
            tenant=tenant,
            quant=quant,
            lot=lot,
            state=payload.state,
            defect_type=defect_type,
            defect_qty=payload.defect_qty,
            description=payload.description,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"id": str(quality_state.id), "state": quality_state.state}


@router.get("/stocks/inventories")
@require_permission("stocks.view_stkinventory")
def list_inventories(request):
    inventories = StkInventory.objects.all().order_by("-date")
    return {
        "results": [
            {
                "id": str(inventory.id),
                "reference": inventory.reference,
                "warehouse_id": str(inventory.warehouse_id),
                "date": inventory.date,
                "type": inventory.type,
                "state": inventory.state,
            }
            for inventory in inventories
        ]
    }


@router.post("/stocks/inventories")
@require_permission("stocks.add_stkinventory")
def create_inventory_endpoint(request, payload: InventoryIn):
    tenant = _tenant(request)
    warehouse = get_object_or_404(StkWarehouse, id=payload.warehouse_id)
    inventory = create_inventory(
        tenant=tenant,
        warehouse=warehouse,
        date=dt.date.fromisoformat(payload.date),
        type=payload.type,
    )
    return {"id": str(inventory.id), "reference": inventory.reference, "state": inventory.state}


@router.post("/stocks/inventories/{inventory_id}/lines")
@require_permission("stocks.change_stkinventory")
def add_inventory_line_endpoint(request, inventory_id: str, payload: InventoryLineIn):
    inventory = get_object_or_404(StkInventory, id=inventory_id)
    location = get_object_or_404(StkLocation, id=payload.location_id)
    lot = get_object_or_404(StkLot, id=payload.lot_id) if payload.lot_id else None
    try:
        line = add_inventory_line(
            inventory, variant_id=uuid.UUID(payload.variant_id), location=location, lot=lot
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"id": str(line.id), "qty_theoretical": line.qty_theoretical}


@router.post("/stocks/inventories/{inventory_id}/validate")
@require_permission("stocks.change_stkinventory")
def validate_inventory_endpoint(request, inventory_id: str):
    inventory = get_object_or_404(StkInventory, id=inventory_id)
    try:
        validate_inventory(inventory, validated_by=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"id": str(inventory.id), "state": inventory.state}


@router.get("/stocks/traceability/{lot_id}")
@require_permission("stocks.view_stklot")
def traceability_endpoint(request, lot_id: str):
    lot = get_object_or_404(StkLot, id=lot_id)
    data = lot_traceability(lot)
    return {
        "lot": {
            "id": str(data["lot"]["id"]),
            "name": data["lot"]["name"],
            "variant_id": str(data["lot"]["variant_id"]),
        },
        "upstream": [{**row, "move_id": str(row["move_id"])} for row in data["upstream"]],
        "downstream": [{**row, "move_id": str(row["move_id"])} for row in data["downstream"]],
        "current_locations": data["current_locations"],
    }


@router.get("/stocks/availability")
@require_permission("stocks.view_stkquant")
def availability_endpoint(
    request, variant: str, qty: Decimal | None = None, date: str | None = None
):
    """`date` accepte pour coller a la liste d'endpoints du CDC (§5.8.6)
    MAIS n'a aucune signification exploitable ici : `StkQuant` est une
    PHOTO INSTANTANEE (cf. sa docstring dans `models.py`), pas un historique
    de disponibilite reconstituable a une date passee — seule la
    disponibilite COURANTE est reellement calculee, `date` est acceptee
    (pour rester compatible avec l'appelant) mais IGNOREE. Documente ici
    honnetement plutot que de repondre silencieusement une valeur fausse
    pour une date passee."""
    variant_id = uuid.UUID(variant)
    return {
        "variant_id": variant,
        "on_hand_qty": on_hand_qty(variant_id),
        "available_qty": available_qty(variant_id),
        "requested_qty": qty,
        "date_ignored": date is not None,
    }


@router.get("/stocks/consistency-report")
@require_permission("stocks.view_stkmove")
def consistency_report_endpoint(request):
    tenant = _tenant(request)
    rows = production_consistency_report(tenant)
    return {
        "results": [
            {
                "order_id": str(row["order_id"]),
                "order_reference": row["order_reference"],
                "qty_declared": row["qty_declared"],
                "qty_entered_stock": row["qty_entered_stock"],
                "variance": row["variance"],
                "anomaly": row["anomaly"],
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# Import quantites initiales depuis Excel (cf. docs/IMPORT_FORMATS.md)
# ---------------------------------------------------------------------------


class StockImportRowResolveIn(Schema):
    variant_code: str | None = None
    warehouse_id: str | None = None
    location_id: str | None = None
    qty: Decimal | None = None
    discard: bool = False


class StockImportRowQualifyIn(Schema):
    variant_id: str | None = None
    location_id: str | None = None


def _serialize_stock_import_row(row: StkImportRow) -> dict:
    return {
        "id": str(row.id),
        "row_number": row.row_number,
        "status": row.status,
        "anomaly_codes": row.anomaly_codes,
        "move_id": str(row.move_id) if row.move_id else None,
        "resolved_variant_id": str(row.resolved_variant_id) if row.resolved_variant_id else None,
        "resolved_location_id": str(row.resolved_location_id) if row.resolved_location_id else None,
        "uses_placeholder_variant": row.uses_placeholder_variant,
        "uses_placeholder_location": row.uses_placeholder_location,
    }


@router.post("/stocks/imports/initial-quantities")
@require_permission("stocks.add_stkimportbatch")
def import_stock_quantities_endpoint(
    request,
    file: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
):
    """Import xlsx des quantites initiales de stock — cf. docstring de
    `services/stock_import.py`/`docs/IMPORT_FORMATS.md`. Meme idiome
    multipart que `accounting.import_cash_journal_endpoint`."""
    tenant = _tenant(request)
    try:
        summary = import_stock_quantities_xlsx(tenant, file.read(), filename=file.name)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    unresolvable_rows = summary.batch.rows.filter(status=StkImportRow.STATUS_UNRESOLVABLE)
    needs_qualification_rows = summary.batch.rows.filter(
        status=StkImportRow.STATUS_NEEDS_QUALIFICATION
    )
    return {
        "batch_id": str(summary.batch.id),
        "total_rows": summary.total_rows,
        "ok_count": summary.ok_count,
        "needs_qualification_count": summary.needs_qualification_count,
        "anomaly_count": summary.unresolvable_count,
        "anomaly_rows": [_serialize_stock_import_row(row) for row in unresolvable_rows],
        "needs_qualification_rows": [
            _serialize_stock_import_row(row) for row in needs_qualification_rows
        ],
    }


@router.post("/stocks/imports/initial-quantities/rows/{row_id}/resolve")
@require_permission("stocks.change_stkimportrow")
def resolve_stock_import_row_endpoint(request, row_id: str, payload: StockImportRowResolveIn):
    """Applique `resolve_import_row` — corrige (entrepot/quantite) ou
    ecarte volontairement une ligne `unresolvable`. Jamais de resolution
    devinee : les valeurs corrigees viennent toujours d'une action
    humaine explicite."""
    row = get_object_or_404(StkImportRow, id=row_id)
    warehouse = (
        get_object_or_404(StkWarehouse, id=payload.warehouse_id) if payload.warehouse_id else None
    )
    location = (
        get_object_or_404(StkLocation, id=payload.location_id) if payload.location_id else None
    )
    resolved = resolve_stock_import_row(
        row,
        variant_code=payload.variant_code,
        warehouse=warehouse,
        location=location,
        qty=payload.qty,
        discard=payload.discard,
    )
    return _serialize_stock_import_row(resolved)


@router.post("/stocks/imports/initial-quantities/rows/{row_id}/qualify")
@require_permission("stocks.qualify_stkimportrow")
def qualify_stock_import_row_endpoint(request, row_id: str, payload: StockImportRowQualifyIn):
    """Applique `qualify_import_row` (chantier RG-QUALIF) — extourne le
    mouvement placeholder deja valide et en recree/valide un nouveau
    correctement attribue (cf. docstring de `services/stock_import.py`).
    L'ACTE D'APPROUVER une qualification en attente passe par l'endpoint
    generique deja existant `POST /api/v1/approvals/{id}/decide`."""
    row = get_object_or_404(StkImportRow, id=row_id)
    location = (
        get_object_or_404(StkLocation, id=payload.location_id) if payload.location_id else None
    )
    variant_id = uuid.UUID(payload.variant_id) if payload.variant_id else None
    try:
        qualified = qualify_stock_import_row(
            row, variant_id=variant_id, location=location, qualified_by=request.auth
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_stock_import_row(qualified)
