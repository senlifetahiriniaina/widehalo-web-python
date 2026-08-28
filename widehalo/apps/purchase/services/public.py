"""Contrat public de l'app `purchase` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Premier gap reellement expose, ajoute pour ST3 de `stocks` (RG-STK-4, cf.
plan) : `open_purchase_incident`, enveloppe fine de
`purchase.services.cri.create_cri` — consomme par
`apps.stocks.services.measurements.record_measurement` pour ouvrir
automatiquement un litige fournisseur quand un ecart de mesure depasse le
seuil parametrable. Remplace le "rien a exposer pour l'instant" de PU1."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.purchase.models import PurOrder
from apps.purchase.services.cri import create_cri


def open_purchase_incident(
    *,
    tenant: Tenant,
    type: str,  # noqa: A002 — coherent avec `create_cri`/`PurCri.type` (nom de champ CDC)
    partner_id: Any,
    description: str,
    order: PurOrder | None = None,
    impact: str = "",
    cost_mga: Decimal = Decimal(0),
) -> UUID:
    """Ouvre un incident fournisseur (`PurCri`, date du jour, `state=draft`)
    et renvoie son UUID — jamais l'objet `PurCri` lui-meme (contrat public,
    regle de couplage n°1). Enveloppe fine sans logique propre : ne
    duplique aucun calcul de `purchase.services.cri.create_cri`, se
    contente de re-exposer ses parametres pertinents pour un appelant
    externe (pas d'`attachment_document_ids` ni d'`action_taken` a ce
    stade — un incident ouvert automatiquement depuis `stocks` n'a ni
    piece jointe ni action corrective au moment de sa creation)."""
    cri = create_cri(
        tenant=tenant,
        date=timezone.now().date(),
        type=type,
        partner_id=partner_id,
        description=description,
        order=order,
        impact=impact,
        cost_mga=cost_mga,
    )
    return cri.id
