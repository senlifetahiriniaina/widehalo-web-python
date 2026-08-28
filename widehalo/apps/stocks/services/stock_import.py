"""Import des quantites initiales de stock (ouverture, migration depuis un
existant externe) depuis un fichier xlsx fourni par l'utilisateur — meme
idiome que `apps.accounting.services.cash_journal_import` : chaque ligne
source produit soit un VRAI `StkMove` de type `TYPE_AJUSTEMENT` deja
VALIDE (`services.moves.create_move` + `validate_move`, jamais
reimplemente ici), soit une anomalie mise en attente de resolution
humaine explicite (`StkImportRow.status=anomaly`) — jamais de resolution
devinee, meme patron que l'import du journal de caisse.

**Pourquoi une file d'anomalies (contrairement a `partners`/`catalog`,
tout-ou-rien)** : une ligne d'ouverture de stock reference TROIS entites
externes au fichier lui-meme (variante produit, entrepot, emplacement) —
exactement le meme besoin "une reference non reconnue ne doit jamais
bloquer les centaines d'autres lignes propres du meme classeur" que la
caisse resolue par ligne dans le journal de tresorerie.

**Emplacement virtuel de contrepartie** : reutilise le meme type
`StkLocation.TYPE_INVENTAIRE` que `services.inventory.validate_inventory`
(ecart d'inventaire) — un stock d'ouverture est conceptuellement identique
a un ecart d'inventaire positif constate au premier comptage : de la
quantite "apparait" sans mouvement d'origine reel. Un emplacement dedie
(code `STOCK-INITIAL`, distinct du `INV-ECART` de l'inventaire) est
cree/reutilise PAR ENTREPOT plutot que de partager celui de l'inventaire,
pour que l'historique d'un mouvement reste explicite sur son origine
("import initial" vs "ecart de comptage") a la lecture d'un rapport de
mouvements.

**Resolution de la variante (regle de couplage n°1)** : jamais d'import
direct de `apps.catalog.models` — `variant_code` est resolu via
`apps.catalog.services.public.get_variant_id_by_reference`, seule surface
autorisee."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.catalog.services.public import get_variant_id_by_reference
from apps.core.models.tenant import Tenant
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows
from apps.stocks.models import (
    StkImportBatch,
    StkImportRow,
    StkLocation,
    StkLot,
    StkMove,
    StkWarehouse,
)
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.warehouses import create_location

STOCK_IMPORT_FORMAT_VERSION = 1

STOCK_IMPORT_HEADER_ALIASES: dict[str, set[str]] = {
    "variant_code": {"VARIANT_CODE", "CODE VARIANTE", "REFERENCE VARIANTE"},
    "warehouse_code": {"WAREHOUSE_CODE", "ENTREPOT", "CODE ENTREPOT"},
    "location_code": {"LOCATION_CODE", "EMPLACEMENT", "CODE EMPLACEMENT"},
    "qty": {"QTY", "QUANTITE", "QUANTITE INITIALE"},
    "unit_cost_mga": {"UNIT_COST_MGA", "COUT UNITAIRE", "COUT UNITAIRE MGA"},
    "lot_reference": {"LOT_REFERENCE", "LOT", "NUMERO DE LOT"},
}

# Anomalies de ligne — memes principes que `cash_journal_import` : chaque
# code doit rester explicite et actionnable par l'utilisateur.
ANOMALY_VARIANTE_INCONNUE = "VARIANTE_INCONNUE"
ANOMALY_ENTREPOT_INCONNU = "ENTREPOT_INCONNU"
ANOMALY_EMPLACEMENT_INCONNU = "EMPLACEMENT_INCONNU"
ANOMALY_QUANTITE_INVALIDE = "QUANTITE_INVALIDE"

_VARIANCE_LOCATION_CODE = "STOCK-INITIAL"


@dataclass
class StockImportSummary:
    batch: StkImportBatch
    total_rows: int
    ok_count: int = 0
    anomaly_count: int = 0


def _resolve_variance_location(warehouse: StkWarehouse) -> StkLocation:
    """Trouve ou cree l'emplacement virtuel `TYPE_INVENTAIRE` dedie a
    l'ouverture de stock de cet entrepot — un seul par entrepot, meme
    patron que `services.inventory._resolve_variance_location` (code
    distinct, cf. docstring de module)."""
    location = StkLocation.objects.filter(
        warehouse=warehouse, type=StkLocation.TYPE_INVENTAIRE, code=_VARIANCE_LOCATION_CODE
    ).first()
    if location is not None:
        return location
    from django.utils.translation import gettext as _

    return create_location(
        tenant=warehouse.tenant,
        warehouse=warehouse,
        code=_VARIANCE_LOCATION_CODE,
        name=_("Stock initial (import)"),
        type=StkLocation.TYPE_INVENTAIRE,
    )


def _resolve_header_index(header: list[str]) -> dict[str, int]:
    normalized = [fold_header(cell) for cell in header]
    resolved: dict[str, int] = {}
    for field_name, aliases in STOCK_IMPORT_HEADER_ALIASES.items():
        folded_aliases = {fold_header(alias) for alias in aliases}
        for index, cell in enumerate(normalized):
            if cell in folded_aliases:
                resolved[field_name] = index
                break
    return resolved


def _normalize_row(row: list[Any], index_by_field: dict[str, int]) -> dict[str, Any]:
    def get(field_name: str) -> Any:
        index = index_by_field.get(field_name)
        if index is None or index >= len(row):
            return None
        value = row[index]
        return value.strip() if isinstance(value, str) else value

    def to_decimal(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    return {
        "variant_code": str(get("variant_code") or "").strip(),
        "warehouse_code": str(get("warehouse_code") or "").strip(),
        "location_code": str(get("location_code") or "").strip(),
        "qty": to_decimal(get("qty")),
        "unit_cost_mga": to_decimal(get("unit_cost_mga")) or Decimal(0),
        "lot_reference": str(get("lot_reference") or "").strip(),
    }


def import_stock_quantities_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = "", format_version: int | None = None
) -> StockImportSummary:
    if format_version is not None and format_version > STOCK_IMPORT_FORMAT_VERSION:
        raise ValueError(
            f"Format d'import de quantités initiales v{format_version} non supporté "
            f"(version maximale supportée : v{STOCK_IMPORT_FORMAT_VERSION}) — "
            "mettez à jour l'application avant de réimporter ce fichier."
        )

    header, data_rows = read_xlsx_rows(file_bytes)
    index_by_field = _resolve_header_index(header)

    batch = StkImportBatch.objects.create(
        tenant=tenant,
        kind=StkImportBatch.KIND_INITIAL_QUANTITIES,
        source_filename=filename,
        format_version=format_version or STOCK_IMPORT_FORMAT_VERSION,
        total_rows=len(data_rows),
    )
    summary = StockImportSummary(batch=batch, total_rows=len(data_rows))

    warehouse_cache: dict[str, StkWarehouse | None] = {}
    variance_location_cache: dict[Any, StkLocation] = {}

    for row_index, row in enumerate(data_rows):
        entry = _normalize_row(row, index_by_field)
        raw_data = {k: (str(v) if v is not None else None) for k, v in entry.items()}
        import_row = StkImportRow.objects.create(
            tenant=tenant, batch=batch, row_number=row_index + 1, raw_data=raw_data
        )

        anomaly_codes: list[str] = []

        variant_id = (
            get_variant_id_by_reference(entry["variant_code"]) if entry["variant_code"] else None
        )
        if variant_id is None:
            anomaly_codes.append(ANOMALY_VARIANTE_INCONNUE)

        warehouse_code = entry["warehouse_code"]
        if warehouse_code not in warehouse_cache:
            warehouse_cache[warehouse_code] = StkWarehouse.objects.filter(
                tenant=tenant, code__iexact=warehouse_code
            ).first()
        warehouse = warehouse_cache[warehouse_code]
        if warehouse is None:
            anomaly_codes.append(ANOMALY_ENTREPOT_INCONNU)

        location = None
        if warehouse is not None:
            location = StkLocation.objects.filter(
                tenant=tenant, warehouse=warehouse, code__iexact=entry["location_code"]
            ).first()
            if location is None:
                anomaly_codes.append(ANOMALY_EMPLACEMENT_INCONNU)

        if entry["qty"] is None or entry["qty"] <= 0:
            anomaly_codes.append(ANOMALY_QUANTITE_INVALIDE)

        if anomaly_codes:
            import_row.status = StkImportRow.STATUS_ANOMALY
            import_row.anomaly_codes = anomaly_codes
            import_row.save(update_fields=["status", "anomaly_codes"])
            summary.anomaly_count += 1
            continue

        assert warehouse is not None and location is not None and variant_id is not None
        assert entry["qty"] is not None

        lot = None
        if entry["lot_reference"]:
            lot, _created = StkLot.objects.get_or_create(
                tenant=tenant, variant_id=variant_id, name=entry["lot_reference"]
            )

        if warehouse.id not in variance_location_cache:
            variance_location_cache[warehouse.id] = _resolve_variance_location(warehouse)
        variance_location = variance_location_cache[warehouse.id]

        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=entry["qty"],
            uom="",
            location_from=variance_location,
            location_to=location,
            date=dt.date.today(),
            move_type=StkMove.TYPE_AJUSTEMENT,
            source_document=f"Import stock initial — {filename or batch.id}",
            unit_cost_mga=entry["unit_cost_mga"],
            lot=lot,
        )
        move = validate_move(move)

        import_row.status = StkImportRow.STATUS_OK
        import_row.move = move
        import_row.save(update_fields=["status", "move"])
        summary.ok_count += 1

    batch.anomaly_rows_count = summary.anomaly_count
    batch.applied_rows_count = summary.ok_count
    batch.save(update_fields=["anomaly_rows_count", "applied_rows_count"])

    return summary


def resolve_import_row(
    row: StkImportRow,
    *,
    variant_code: str | None = None,
    warehouse: StkWarehouse | None = None,
    location: StkLocation | None = None,
    qty: Decimal | None = None,
    discard: bool = False,
) -> StkImportRow:
    """Corrige manuellement une ligne en anomalie puis retente sa
    materialisation — jamais de resolution automatique/devinee : c'est
    toujours un humain qui fournit la variante/l'entrepot/l'emplacement/la
    quantite corriges ici (meme discipline exacte que
    `cash_journal_import.resolve_import_row`)."""
    if discard:
        row.status = StkImportRow.STATUS_DISCARDED
        row.save(update_fields=["status"])
        return row

    raw = dict(row.raw_data)
    tenant = row.tenant

    resolved_variant_id = (
        get_variant_id_by_reference(variant_code)
        if variant_code
        else get_variant_id_by_reference(raw.get("variant_code") or "")
    )
    resolved_location = location
    if resolved_location is None and warehouse is not None:
        resolved_location = StkLocation.objects.filter(
            tenant=tenant, warehouse=warehouse, code__iexact=raw.get("location_code") or ""
        ).first()
    resolved_qty = qty
    if resolved_qty is None:
        try:
            resolved_qty = Decimal(raw.get("qty") or "0")
        except InvalidOperation:
            resolved_qty = None
    try:
        unit_cost_mga = Decimal(raw.get("unit_cost_mga") or "0")
    except InvalidOperation:
        unit_cost_mga = Decimal(0)

    anomaly_codes: list[str] = []
    if resolved_variant_id is None:
        anomaly_codes.append(ANOMALY_VARIANTE_INCONNUE)
    if warehouse is None:
        anomaly_codes.append(ANOMALY_ENTREPOT_INCONNU)
    if resolved_location is None:
        anomaly_codes.append(ANOMALY_EMPLACEMENT_INCONNU)
    if resolved_qty is None or resolved_qty <= 0:
        anomaly_codes.append(ANOMALY_QUANTITE_INVALIDE)

    if anomaly_codes:
        row.status = StkImportRow.STATUS_ANOMALY
        row.anomaly_codes = anomaly_codes
        row.save(update_fields=["status", "anomaly_codes"])
        return row

    assert warehouse is not None and resolved_location is not None
    assert resolved_variant_id is not None and resolved_qty is not None

    lot = None
    lot_reference = raw.get("lot_reference") or ""
    if lot_reference:
        lot, _created = StkLot.objects.get_or_create(
            tenant=tenant, variant_id=resolved_variant_id, name=lot_reference
        )

    variance_location = _resolve_variance_location(warehouse)
    move = create_move(
        tenant=tenant,
        variant_id=resolved_variant_id,
        qty=resolved_qty,
        uom="",
        location_from=variance_location,
        location_to=resolved_location,
        date=dt.date.today(),
        move_type=StkMove.TYPE_AJUSTEMENT,
        source_document=f"Import stock initial (résolution) — {row.batch_id}",
        unit_cost_mga=unit_cost_mga,
        lot=lot,
    )
    move = validate_move(move)

    row.status = StkImportRow.STATUS_RESOLVED
    row.move = move
    row.anomaly_codes = []
    row.save(update_fields=["status", "move", "anomaly_codes"])
    return row
