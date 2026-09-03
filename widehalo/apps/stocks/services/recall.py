"""A3 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) : rappel
produit — RG-STK-11.

"Un lot suspect permet de lister en < 5 s tous les lots finis et clients
impactés (traçabilité one-up/one-back)" : réutilise entièrement
`services.genealogy.genealogy_tree` (A2, déjà construit précisément pour
ce besoin — cf. son docstring de module) pour descendre la chaîne de
transformation, et `services.traceability.lot_traceability` (A1/ST8, déjà
construit) pour la partie "clients livrés" de chaque lot impacté. Aucune
nouvelle logique de traçabilité n'est réinventée ici — ce module ne fait
que COMPOSER les deux, déclarer l'incident (`StkRecall`) et déclencher le
blocage physique (`services.moves.create_move`, via `StkLot.is_held()`,
RG-STK-11)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone

from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.stocks.models import StkLot, StkMove, StkQualityState, StkRecall
from apps.stocks.services.genealogy import genealogy_tree
from apps.stocks.services.quality import set_quality_state
from apps.stocks.services.traceability import lot_traceability


def _descendant_lots(lot: StkLot) -> list[StkLot]:
    """Liste À PLAT (BFS, dédupliquée) de tous les lots descendants de
    `lot`, réutilisant `genealogy_tree` plutôt que de reparcourir
    `StkLotGenealogy` soi-même — une seule implémentation de la descente
    généalogique dans tout le module."""
    tree = genealogy_tree(lot)
    lot_ids: list[Any] = []

    def _walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            lot_ids.append(node["lot_id"])
            _walk(node["children"])

    _walk(tree["descendants"])
    return list(StkLot.objects.filter(tenant=lot.tenant, id__in=lot_ids))


def declare_recall(
    *, lot: StkLot, reason: str, initiated_by: User | None = None, date: dt.date | None = None
) -> StkRecall:
    """Déclare un rappel produit sur `lot` : calcule le périmètre impacté
    (`lot` lui-même + tous ses descendants), le fige dans `StkRecall`
    (jamais recalculé après coup, cf. docstring du modèle), place chaque
    lot impacté en quarantaine (`StkQualityState.STATE_EN_QUARANTAINE` —
    RG-STK-11, aussitôt appliqué par la garde de `services.moves.
    create_move`) et journalise l'exposition client connue à cet instant."""
    date = date or timezone.now().date()
    impacted_lots = [lot, *_descendant_lots(lot)]

    client_exposures: list[dict[str, Any]] = []
    for impacted in impacted_lots:
        trace = lot_traceability(impacted)
        for move in trace["downstream"]:
            if move["move_type"] == StkMove.TYPE_LIVRAISON:
                client_exposures.append(
                    {
                        "lot_name": impacted.name,
                        "source_document": move["source_document"],
                        "qty": str(move["qty"]),
                    }
                )
        set_quality_state(
            tenant=lot.tenant,
            lot=impacted,
            state=StkQualityState.STATE_EN_QUARANTAINE,
            description=f"Rappel produit {lot.name} : {reason}",
            decided_by=initiated_by,
        )

    reference = next_reference(lot.tenant, "RECALL", date.year)
    return StkRecall.objects.create(
        tenant=lot.tenant,
        reference=reference,
        lot=lot,
        reason=reason,
        initiated_by=initiated_by,
        impacted_lot_ids=[str(impacted.id) for impacted in impacted_lots],
        impacted_lot_names=[impacted.name for impacted in impacted_lots],
        client_exposures=client_exposures,
    )


def close_recall(recall: StkRecall, *, closed_by: User | None = None) -> StkRecall:
    """Clôture le rappel — n'annule PAS automatiquement la mise en
    quarantaine des lots impactés (une décision de libération par lot
    reste une décision qualité distincte et délibérée, `services.quality.
    set_quality_state(..., state=STATE_CONFORME)`, jamais un effet de bord
    silencieux de la clôture administrative du dossier de rappel)."""
    recall.state = StkRecall.STATE_CLOSED
    recall.closed_by = closed_by
    recall.closed_at = timezone.now()
    recall.save(update_fields=["state", "closed_by", "closed_at"])
    return recall
