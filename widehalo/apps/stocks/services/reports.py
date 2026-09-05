"""Rapports `stocks` (§5.8.5, ST8 — dernier lot de `stocks`) : STK-ETAT,
STK-MOUV, STK-TRAC, STK-INV, STK-DEF, STK-AGE, STK-COHER, STK-MES, STK-VAL.

`rows_to_bytes` est une COPIE volontaire du helper identique de
`apps.purchase.services.reports`/`apps.sales.services.reports`/
`apps.mrp.services.reports` (deja duplique par app dans ce projet, jamais
centralise dans `core`, verifie avant d'ecrire ce fichier) — suivre la
convention existante plutot que d'introduire une nouvelle dependance
inter-app pour un utilitaire generique.

Tous les rapports de ce fichier sont des exports TABULAIRES json/csv/xlsx
(pas de PDF) — `stocks` ne produit aucun document destine a etre signe par
un tiers (a la difference de `PUR-BC`), uniquement des rapports d'analyse/
pilotage internes, meme choix que SAL-CA/SAL-MARGE/etc."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Count, Sum

from apps.core.models.tenant import Tenant
from apps.stocks.models import (
    StkInventory,
    StkInventoryLine,
    StkLocation,
    StkLot,
    StkMeasurement,
    StkMove,
    StkQualityState,
    StkQuant,
    StkValuationLayer,
)
from apps.stocks.services.consistency import production_consistency_report
from apps.stocks.services.obsolescence import dormant_stock_report
from apps.stocks.services.traceability import lot_traceability


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


def stock_state_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """STK-ETAT — etat des stocks valorise par emplacement (et produit) :
    somme de `StkQuant.qty`/`value_mga` par (emplacement, variant), tous
    lots confondus, restreint aux emplacements INTERNES (un etat de stock
    "valorise" n'a de sens que pour du stock reellement possede, cf.
    docstring `StkQuant`/`services.quants.on_hand_qty`).

    **Dimension "famille" honnetement absente** : le CDC (§5.8.5) demande
    un etat "par emplacement et FAMILLE" — `stocks` ne possede aucune
    notion de famille/categorie produit (`apps.catalog.models.Category`,
    hors perimetre, regle de couplage n°1 : jamais de FK ni de jointure
    directe vers `catalog`). Plutot que d'inventer une jointure qui
    afficherait une precision qu'il n'a pas les moyens de garantir, ce
    rapport expose la dimension `variant_id` (le niveau de granularite
    reel que `stocks` connait nativement) — un futur enrichissement cote
    ecran pourrait resoudre `variant_id` -> famille via
    `catalog.services.public` si un besoin precis se presente, mais ce
    rapport lui-meme reste honnete sur ce qu'il sait calculer seul."""
    rows = (
        StkQuant.objects.filter(tenant=tenant, location__type=StkLocation.TYPE_INTERNE)
        .values("location_id", "variant_id")
        .annotate(qty=Sum("qty"), value_mga=Sum("value_mga"))
        .order_by("location_id", "variant_id")
    )
    return [
        {
            "location_id": row["location_id"],
            "variant_id": row["variant_id"],
            "qty": row["qty"] or Decimal(0),
            "value_mga": row["value_mga"] or Decimal(0),
        }
        for row in rows
    ]


def move_rows(
    tenant: Tenant,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    variant_id: UUID | None = None,
    move_type: str = "",
) -> list[dict[str, Any]]:
    """STK-MOUV — journal des mouvements, filtrable par periode/produit/
    type. Expose TOUS les champs du mouvement (CDC : "au minimum exposer
    tous les champs")."""
    moves = StkMove.objects.filter(tenant=tenant).order_by("date", "id")
    if date_from is not None:
        moves = moves.filter(date__gte=date_from)
    if date_to is not None:
        moves = moves.filter(date__lte=date_to)
    if variant_id is not None:
        moves = moves.filter(variant_id=variant_id)
    if move_type:
        moves = moves.filter(move_type=move_type)
    return [
        {
            "reference": move.reference,
            "date": move.date,
            "move_type": move.move_type,
            "state": move.state,
            "variant_id": move.variant_id,
            "lot_id": move.lot_id,
            "qty": move.qty,
            "uom": move.uom,
            "location_from_id": move.location_from_id,
            "location_to_id": move.location_to_id,
            "unit_cost_mga": move.unit_cost_mga,
            "value_mga": move.value_mga,
            "source_document": move.source_document,
        }
        for move in moves
    ]


def traceability_rows(lot: StkLot) -> list[dict[str, Any]]:
    """STK-TRAC — mise a plat tabulaire de `services.traceability.
    lot_traceability` : une ligne par mouvement amont/aval, plus une ligne
    par emplacement courant (`direction="localisation"`), pour un export
    unique coherent avec le format `rows_to_bytes` commun a ce fichier."""
    data = lot_traceability(lot)
    rows: list[dict[str, Any]] = []
    for move in data["upstream"]:
        rows.append({"direction": "amont", **move, "location_id": None, "qty_location": None})
    for move in data["downstream"]:
        rows.append({"direction": "aval", **move, "location_id": None, "qty_location": None})
    for location in data["current_locations"]:
        rows.append(
            {
                "direction": "localisation",
                "move_id": None,
                "reference": None,
                "date": None,
                "move_type": None,
                "qty": None,
                "location_from_id": None,
                "location_to_id": None,
                "source_document": None,
                "location_id": location["location_id"],
                "qty_location": location["qty"],
            }
        )
    return rows


def inventory_line_rows(inventory: StkInventory) -> list[dict[str, Any]]:
    """STK-INV — feuille d'inventaire et ecarts : toutes les lignes de
    `inventory`.

    **La fuite la plus concrete que L13 ferme** (STK-6). L'ecran masquait la
    quantite attendue pendant le comptage, et proposait juste en dessous un
    lien « Telecharger la feuille d'inventaire » qui la restituait en clair.
    Un compteur contournait donc le mode aveugle en un clic, sans rien faire
    d'anormal.

    La decision de masquer vit sur le modele
    (`StkInventory.hides_expected_quantity`), une seule fois, precisement
    parce qu'elle etait deja prise a deux endroits differents et qu'un
    troisieme l'avait oubliee."""
    hidden = inventory.hides_expected_quantity
    lines = StkInventoryLine.objects.filter(inventory=inventory).order_by("location_id", "id")
    return [
        {
            "variant_id": line.variant_id,
            "lot_id": line.lot_id,
            "location_id": line.location_id,
            "qty_theoretical": None if hidden else line.qty_theoretical,
            "qty_counted": line.qty_counted,
            "difference": None if hidden else line.difference,
            "reason": line.reason,
        }
        for line in lines
    ]


def defect_analysis_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """STK-DEF — analyse des defauts par type (`StkDefectType`).

    **Dimension "par fournisseur" honnetement absente** : le CDC (§5.8.5)
    demande une analyse "par type ET par fournisseur" — `StkQualityState`
    (ni `StkQuant` dont elle depend) ne porte AUCUN `partner_id` : un etat
    qualite est attache a un quant/lot precis, jamais a la reception
    fournisseur qui l'a genere (`StkMove.source_document` porte bien une
    reference libre, mais aucune garantie qu'un `StkQualityState` donne se
    rattache a un `StkMove`/`source_document` precis — rien dans ce depot
    ne relie une classification qualite a UNE reception fournisseur
    identifiee). Fabriquer cette jointure via une correspondance
    approximative (ex. "le dernier mouvement recu sur ce quant") afficherait
    une precision que les donnees ne garantissent pas — meme discipline
    d'honnetete que la 3e jambe de RG-STK-6 (cf. docstring
    `services/consistency.py`). Ce rapport se limite donc a la dimension
    `defect_type`/`category`/`severity`, la seule fiable, la dimension
    fournisseur restant NON DERIVABLE dans ce lot."""
    rows = (
        StkQualityState.objects.filter(tenant=tenant, defect_type__isnull=False)
        .values("defect_type__code", "defect_type__name", "defect_type__category", "state")
        .annotate(total_qty=Sum("defect_qty"), count=Count("id"))
        .order_by("defect_type__category", "defect_type__code")
    )
    return [
        {
            "defect_type_code": row["defect_type__code"],
            "defect_type_name": row["defect_type__name"],
            "category": row["defect_type__category"],
            "state": row["state"],
            "total_qty": row["total_qty"] or Decimal(0),
            "count": row["count"] or 0,
        }
        for row in rows
    ]


def dormant_stock_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """STK-AGE — expose `services.obsolescence.dormant_stock_report` tel
    quel, aucun recalcul duplique ici."""
    return dormant_stock_report(tenant)


def production_consistency_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """STK-COHER — expose `services.consistency.production_consistency_
    report` tel quel, aucun recalcul duplique ici."""
    return production_consistency_report(tenant)


def measurement_variance_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """STK-MES — ecarts de mesure fournisseurs : mesures dont
    `variance_pct` est renseigne ET non nul, tri decroissant par ecart
    ABSOLU (les ecarts les plus significatifs en tete). Choix retenu (parmi
    les deux options laissees ouvertes par la consigne) : ce rapport est un
    rapport d'ANOMALIE de mesure (le nom CDC "ecarts de mesure" le suggere
    litteralement), pas un journal exhaustif de toutes les mesures — une
    mesure sans ecart calcule (`variance_pct is None`, ex. simple controle
    d'inventaire sans theorique de reference) ou avec un ecart nul n'a rien
    a apporter a une analyse d'ecart."""
    measurements = (
        StkMeasurement.objects.filter(tenant=tenant)
        .exclude(variance_pct__isnull=True)
        .exclude(variance_pct=0)
        .order_by("-variance_pct")
    )
    return [
        {
            "measured_at": measurement.measured_at,
            "type": measurement.type,
            "value": measurement.value,
            "uom": measurement.uom,
            "variance_pct": measurement.variance_pct,
            "device": measurement.device,
        }
        for measurement in measurements
    ]


def valuation_layer_rows(tenant: Tenant, *, variant_id: UUID | None = None) -> list[dict[str, Any]]:
    """STK-VAL — valorisation detaillee par couche FIFO/CMP, filtrable par
    produit — utile pour un audit FIFO (verifier `remaining_qty`/
    `remaining_value_mga` couche par couche)."""
    layers = StkValuationLayer.objects.filter(tenant=tenant).order_by("variant_id", "date", "id")
    if variant_id is not None:
        layers = layers.filter(variant_id=variant_id)
    return [
        {
            "variant_id": layer.variant_id,
            "date": layer.date,
            "qty": layer.qty,
            "unit_cost_mga": layer.unit_cost_mga,
            "value_mga": layer.value_mga,
            "remaining_qty": layer.remaining_qty,
            "remaining_value_mga": layer.remaining_value_mga,
        }
        for layer in layers
    ]
