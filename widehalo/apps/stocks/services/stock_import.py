"""Import des quantites initiales de stock (ouverture, migration depuis un
existant externe) depuis un fichier xlsx fourni par l'utilisateur — meme
idiome que `apps.accounting.services.cash_journal_import` : chaque ligne
source produit soit un VRAI `StkMove` de type `TYPE_AJUSTEMENT` deja
VALIDE (`services.moves.create_move` + `validate_move`, jamais
reimplemente ici), soit une anomalie mise en attente de resolution
humaine explicite (`StkImportRow.status=unresolvable`), meme patron que
l'import du journal de caisse.

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
autorisee.

**Chantier RG-QUALIF (qualification et identification universelle des
donnees importees)** — retrofit de ce module, registre defaultable/
non-defaultable complet dans `docs/IMPORT_FORMATS.md` §6 :

- `VARIANTE_INCONNUE` : DEfaultable — repli sur la variante placeholder
  (`catalog.services.public.ensure_default_variant`), `uses_placeholder_
  variant=True`.
- `EMPLACEMENT_INCONNU` : DEfaultable — repli sur l'emplacement virtuel
  "Zone à qualifier" de l'entrepot (`services.defaults.
  ensure_unqualified_location`), `uses_placeholder_location=True`.
- `ENTREPOT_INCONNU` : non-defaultable — aucun entrepot par defaut sûr
  (un `StkMove` a TOUJOURS besoin d'un entrepot reel pour ses deux
  emplacements, RG-STK-1).
- `QUANTITE_INVALIDE` : non-defaultable — inventer une quantite
  fabriquerait un fait de stock.

**Qualification apres coup (`qualify_import_row`)** : contrairement au
journal de caisse (ecriture toujours `draft`, editable), un `StkMove`
d'ouverture est VALIDE immediatement (quants deja mis a jour) — remplacer
un placeholder ne peut donc jamais se faire par simple edition du
mouvement existant (corromprait les quants deja poses). `qualify_import_
row` EXTOURNE le mouvement placeholder (`services.moves.reverse_move`,
meme patron que toute correction post-validation de ce module) puis cree
et valide un nouveau `StkMove` avec la variante/l'emplacement reels."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.catalog.services.public import ensure_default_variant, get_variant_id_by_reference
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services import approvals
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows
from apps.stocks.models import (
    StkImportBatch,
    StkImportRow,
    StkLocation,
    StkLot,
    StkMove,
    StkWarehouse,
)
from apps.stocks.services.defaults import ensure_unqualified_location
from apps.stocks.services.moves import create_move, reverse_move, validate_move
from apps.stocks.services.warehouses import create_location

STOCK_IMPORT_FORMAT_VERSION = 1

QUALIFICATION_RULE_NAME = "stocks.stkimportrow.qualification"

STOCK_IMPORT_HEADER_ALIASES: dict[str, set[str]] = {
    "variant_code": {"VARIANT_CODE", "CODE VARIANTE", "REFERENCE VARIANTE"},
    "warehouse_code": {"WAREHOUSE_CODE", "ENTREPOT", "CODE ENTREPOT"},
    "location_code": {"LOCATION_CODE", "EMPLACEMENT", "CODE EMPLACEMENT"},
    "qty": {"QTY", "QUANTITE", "QUANTITE INITIALE"},
    "unit_cost_mga": {"UNIT_COST_MGA", "COUT UNITAIRE", "COUT UNITAIRE MGA"},
    "lot_reference": {"LOT_REFERENCE", "LOT", "NUMERO DE LOT"},
}

# Anomalies de ligne — memes principes que `cash_journal_import` : chaque
# code doit rester explicite et actionnable par l'utilisateur, cf.
# docs/IMPORT_FORMATS.md §6 pour le registre defaultable/non-defaultable.
ANOMALY_VARIANTE_INCONNUE = "VARIANTE_INCONNUE"
ANOMALY_ENTREPOT_INCONNU = "ENTREPOT_INCONNU"
ANOMALY_EMPLACEMENT_INCONNU = "EMPLACEMENT_INCONNU"
ANOMALY_QUANTITE_INVALIDE = "QUANTITE_INVALIDE"

# Codes non-defaultables (cf. docstring de module) : une ligne qui en porte
# un ne produit JAMAIS de `StkMove`, reste `STATUS_UNRESOLVABLE`.
_BLOCKING_ANOMALY_CODES = {ANOMALY_ENTREPOT_INCONNU, ANOMALY_QUANTITE_INVALIDE}

_VARIANCE_LOCATION_CODE = "STOCK-INITIAL"


@dataclass
class StockImportSummary:
    batch: StkImportBatch
    total_rows: int
    ok_count: int = 0
    needs_qualification_count: int = 0
    unresolvable_count: int = 0


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

    return create_location(
        tenant=warehouse.tenant,
        warehouse=warehouse,
        code=_VARIANCE_LOCATION_CODE,
        name=str(_("Stock initial (import)")),
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


def _resolve_variant(tenant: Tenant, variant_code: str) -> tuple[UUID, bool, list[str]]:
    """Retourne `(variant_id, uses_placeholder, codes_anomalie)` — jamais
    bloquant depuis RG-QUALIF : un code non reconnu (ou absent) retombe
    sur la variante placeholder du tenant."""
    variant_id = get_variant_id_by_reference(variant_code) if variant_code else None
    if variant_id is not None:
        return variant_id, False, []
    return ensure_default_variant(tenant), True, [ANOMALY_VARIANTE_INCONNUE]


def _resolve_location(
    tenant: Tenant, warehouse: StkWarehouse, location_code: str
) -> tuple[StkLocation, bool, list[str]]:
    """Retourne `(location, uses_placeholder, codes_anomalie)` — jamais
    bloquant depuis RG-QUALIF tant qu'un entrepot est identifie : un code
    d'emplacement non reconnu retombe sur la "Zone à qualifier" de cet
    entrepot."""
    location = StkLocation.objects.filter(
        tenant=tenant, warehouse=warehouse, code__iexact=location_code
    ).first()
    if location is not None:
        return location, False, []
    return ensure_unqualified_location(warehouse), True, [ANOMALY_EMPLACEMENT_INCONNU]


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

        warehouse_code = entry["warehouse_code"]
        if warehouse_code not in warehouse_cache:
            warehouse_cache[warehouse_code] = StkWarehouse.objects.filter(
                tenant=tenant, code__iexact=warehouse_code
            ).first()
        warehouse = warehouse_cache[warehouse_code]
        if warehouse is None:
            anomaly_codes.append(ANOMALY_ENTREPOT_INCONNU)

        if entry["qty"] is None or entry["qty"] <= 0:
            anomaly_codes.append(ANOMALY_QUANTITE_INVALIDE)

        if any(code in _BLOCKING_ANOMALY_CODES for code in anomaly_codes):
            import_row.status = StkImportRow.STATUS_UNRESOLVABLE
            import_row.anomaly_codes = anomaly_codes
            import_row.save(update_fields=["status", "anomaly_codes"])
            summary.unresolvable_count += 1
            continue

        assert warehouse is not None and entry["qty"] is not None

        variant_id, uses_placeholder_variant, variant_codes = _resolve_variant(
            tenant, entry["variant_code"]
        )
        anomaly_codes.extend(variant_codes)
        location, uses_placeholder_location, location_codes = _resolve_location(
            tenant, warehouse, entry["location_code"]
        )
        anomaly_codes.extend(location_codes)

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

        needs_qualification = uses_placeholder_variant or uses_placeholder_location
        import_row.status = (
            StkImportRow.STATUS_NEEDS_QUALIFICATION
            if needs_qualification
            else StkImportRow.STATUS_OK
        )
        import_row.move = move
        import_row.resolved_variant_id = variant_id
        import_row.resolved_location = location
        import_row.uses_placeholder_variant = uses_placeholder_variant
        import_row.uses_placeholder_location = uses_placeholder_location
        import_row.anomaly_codes = anomaly_codes
        import_row.save(
            update_fields=[
                "status",
                "move",
                "resolved_variant_id",
                "resolved_location",
                "uses_placeholder_variant",
                "uses_placeholder_location",
                "anomaly_codes",
            ]
        )
        if needs_qualification:
            summary.needs_qualification_count += 1
        else:
            summary.ok_count += 1

    batch.anomaly_rows_count = summary.unresolvable_count
    batch.applied_rows_count = summary.ok_count + summary.needs_qualification_count
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
    """Corrige manuellement une ligne `unresolvable` (entrepot/quantite
    invalides — les seuls cas restant bloquants depuis RG-QUALIF, cf.
    docstring de module) puis retente sa materialisation — jamais de
    resolution devinee : c'est toujours un humain qui fournit
    l'entrepot/l'emplacement/la quantite corriges ici."""
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
    if resolved_variant_id is None:
        resolved_variant_id = ensure_default_variant(tenant)
        uses_placeholder_variant = True
    else:
        uses_placeholder_variant = False

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
    if warehouse is None:
        anomaly_codes.append(ANOMALY_ENTREPOT_INCONNU)
    if resolved_qty is None or resolved_qty <= 0:
        anomaly_codes.append(ANOMALY_QUANTITE_INVALIDE)

    if anomaly_codes:
        row.status = StkImportRow.STATUS_UNRESOLVABLE
        row.anomaly_codes = anomaly_codes
        row.save(update_fields=["status", "anomaly_codes"])
        return row

    assert warehouse is not None and resolved_qty is not None

    resolved_location = location
    uses_placeholder_location = False
    if resolved_location is None:
        resolved_location, uses_placeholder_location, _codes = _resolve_location(
            tenant, warehouse, raw.get("location_code") or ""
        )

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
    row.resolved_variant_id = resolved_variant_id
    row.resolved_location = resolved_location
    row.uses_placeholder_variant = uses_placeholder_variant
    row.uses_placeholder_location = uses_placeholder_location
    row.anomaly_codes = []
    row.save(
        update_fields=[
            "status",
            "move",
            "resolved_variant_id",
            "resolved_location",
            "uses_placeholder_variant",
            "uses_placeholder_location",
            "anomaly_codes",
        ]
    )
    return row


def ensure_qualification_approval_rule(tenant: Tenant) -> ApprovalRule:
    """Cree, si elle n'existe pas encore, LA regle d'approbation de
    qualification des lignes d'import de stock pour ce tenant —
    idempotente, scopee au content-type `StkImportRow`, condition
    `requires_placeholder` (meme patron que `accounting.services.
    cash_journal_import.ensure_qualification_approval_rule`). Approbateur
    par defaut : `direction`, qualifiable par `magasinier` (domaine cible
    du module, cf. `rbac_policy.ROLE_APP_PERMISSIONS`)."""
    content_type = ContentType.objects.get_for_model(StkImportRow)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=QUALIFICATION_RULE_NAME,
        defaults={"approver_role": "direction", "condition": {"requires_placeholder": True}},
    )
    return rule


def qualify_import_row(
    row: StkImportRow,
    *,
    variant_id: UUID | None = None,
    location: StkLocation | None = None,
    qualified_by: User,
) -> StkImportRow:
    """Remplace le(s) placeholder(s) d'une ligne `needs_qualification` par
    l'entite reelle fournie par l'utilisateur. Contrairement au journal de
    caisse (`AccMove` toujours `draft`), le `StkMove` d'ouverture est deja
    VALIDE (quants poses) — remplacer un placeholder EXTOURNE donc le
    mouvement placeholder (`services.moves.reverse_move`) puis cree et
    valide un nouveau `StkMove` correctement attribue, plutot que
    d'editer le mouvement existant (corromprait les quants deja poses).

    **Simplification v1 assumee** : toute dimension encore placeholder de
    la ligne doit etre fournie EN UNE SEULE fois (le mouvement est
    extourne/recree globalement, pas dimension par dimension) — sinon
    `ValidationError`."""
    if row.status != StkImportRow.STATUS_NEEDS_QUALIFICATION:
        raise ValidationError(_("Seule une ligne « à qualifier » peut être qualifiée."))
    move = row.move
    if move is None:
        raise ValidationError(_("Cette ligne n'a pas de mouvement associé à qualifier."))
    if row.uses_placeholder_variant and variant_id is None:
        raise ValidationError(_("La variante réelle doit être fournie pour qualifier cette ligne."))
    if row.uses_placeholder_location and location is None:
        raise ValidationError(_("L'emplacement réel doit être fourni pour qualifier cette ligne."))

    requires_approval = row.uses_placeholder_variant or row.uses_placeholder_location

    reverse_move(move)
    new_variant_id = variant_id if row.uses_placeholder_variant else move.variant_id
    new_location = location if row.uses_placeholder_location else move.location_to
    assert new_variant_id is not None and new_location is not None

    new_move = create_move(
        tenant=row.tenant,
        variant_id=new_variant_id,
        qty=move.qty,
        uom=move.uom,
        location_from=move.location_from,
        location_to=new_location,
        date=move.date,
        move_type=StkMove.TYPE_AJUSTEMENT,
        source_document=f"Qualification — {row.batch_id}",
        unit_cost_mga=move.unit_cost_mga,
        lot=move.lot,
    )
    new_move = validate_move(new_move)

    row.move = new_move
    row.resolved_variant_id = new_variant_id
    row.resolved_location = new_location
    row.uses_placeholder_variant = False
    row.uses_placeholder_location = False

    update_fields = [
        "move",
        "resolved_variant_id",
        "resolved_location",
        "uses_placeholder_variant",
        "uses_placeholder_location",
        "status",
    ]

    if requires_approval:
        rule = ensure_qualification_approval_rule(row.tenant)
        if rule.is_active:
            approval_request = approvals.request_approval(row, rule, qualified_by)
            row.status = StkImportRow.STATUS_PENDING_APPROVAL
            row.qualification_approval_request = approval_request
            update_fields.append("qualification_approval_request")
            row.save(update_fields=update_fields)
            return row

    row.status = StkImportRow.STATUS_QUALIFIED
    row.save(update_fields=update_fields)
    return row


def decide_qualification(
    approval_request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> StkImportRow:
    """Enveloppe fine de `apps.core.services.approvals.decide` qui met
    aussi a jour le statut de la ligne d'import qualifiee — meme patron
    que `accounting.services.cash_journal_import.decide_qualification`."""
    approvals.decide(approval_request, decided_by, approved=approved, comment=comment)
    row = StkImportRow.objects.get(qualification_approval_request=approval_request)
    row.status = (
        StkImportRow.STATUS_QUALIFIED if approved else StkImportRow.STATUS_NEEDS_QUALIFICATION
    )
    row.save(update_fields=["status"])
    return row
