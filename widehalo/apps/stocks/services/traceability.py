"""Tracabilite ascendante/descendante d'un lot (§5.8, ST8 du
sous-sequencement `stocks` — cf. plan) : acceptance test §5.8.7 n°5 —
"La tracabilite d'un lot de tissu remonte a la commande fournisseur et
descend jusqu'aux clients livres."

**Construction a partir de `StkMove`/`StkMove.source_document` uniquement**
— aucune nouvelle entite, aucune resolution cross-app. Meme convention de
correlation par CHAINE que `services.consistency.production_consistency_
report` (cf. sa docstring) : `stocks` ne resout jamais lui-meme
`source_document` vers un objet reel `purchase`/`sales` (regle de couplage
n°1) — il se contente de SURFACER la chaine telle qu'enregistree par
l'appelant qui a cree le mouvement (une reception dont `source_document`
porte la reference de la commande fournisseur d'origine, une livraison
dont `source_document` porte la reference de la commande client). C'est un
choix de lecture READ-ONLY pur : `lot_traceability` n'ecrit jamais rien,
elle agrege l'historique `StkMove` deja existant pour `lot`.

**"Amont"/"aval"** : amont = tous les mouvements `done` de type
`reception` (ou `sous_traitance`, un retour de sous-traitance est aussi une
entree amont) portant ce lot ; aval = tous les mouvements `done` de type
`livraison` (ou `retour`, un retour client documente egalement un aval —
la sortie initiale reste tracee par la livraison elle-meme, le retour
n'annule pas l'historique). Tries chronologiquement (`date`, puis `id` a
date egale, meme ordre stable que `services.moves._consume_fifo_layers`)."""

from __future__ import annotations

from typing import Any

from apps.stocks.models import StkLocation, StkLot, StkMove, StkQuant

# Types de mouvement consideres comme "amont" (entree dans le perimetre
# trace, remontant vers la commande fournisseur d'origine) et "aval"
# (sortie vers le client), cf. docstring de module.
_UPSTREAM_MOVE_TYPES = (StkMove.TYPE_RECEPTION, StkMove.TYPE_SOUS_TRAITANCE)
_DOWNSTREAM_MOVE_TYPES = (StkMove.TYPE_LIVRAISON, StkMove.TYPE_RETOUR)


def _serialize_move(move: StkMove) -> dict[str, Any]:
    return {
        "move_id": move.id,
        "reference": move.reference,
        "date": move.date,
        "move_type": move.move_type,
        "qty": move.qty,
        "location_from_id": move.location_from_id,
        "location_to_id": move.location_to_id,
        "source_document": move.source_document,
    }


def lot_traceability(lot: StkLot) -> dict[str, Any]:
    """Agrege, pour `lot`, l'amont (receptions/sous-traitance -> reference
    de commande fournisseur portee par `source_document`), l'aval
    (livraisons/retours -> reference de commande client portee par
    `source_document`) et les emplacements courants ou ce lot est
    physiquement present (`StkQuant.qty > 0`).

    Read-only pur — n'effectue AUCUNE ecriture, ne cree ni ne modifie aucun
    `StkMove`/`StkQuant`."""
    moves = StkMove.objects.filter(tenant=lot.tenant, lot=lot, state=StkMove.STATE_DONE).order_by(
        "date", "id"
    )
    upstream = [_serialize_move(m) for m in moves if m.move_type in _UPSTREAM_MOVE_TYPES]
    downstream = [_serialize_move(m) for m in moves if m.move_type in _DOWNSTREAM_MOVE_TYPES]

    current_locations = [
        {
            "location_id": quant.location_id,
            "location_code": quant.location.code,
            "qty": quant.qty,
        }
        for quant in StkQuant.objects.filter(
            tenant=lot.tenant, lot=lot, qty__gt=0, location__type=StkLocation.TYPE_INTERNE
        ).select_related("location")
    ]

    return {
        "lot": {
            "id": lot.id,
            "name": lot.name,
            "variant_id": lot.variant_id,
            "date_production": lot.date_production,
            "date_expiry": lot.date_expiry,
            "supplier_lot": lot.supplier_lot,
        },
        "upstream": upstream,
        "downstream": downstream,
        "current_locations": current_locations,
    }
