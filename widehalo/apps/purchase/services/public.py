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


def get_order_reference(order_id: Any) -> str:
    """Gap ajoute pour LOG4 de `logistics` (cf. plan, audit LOG4) :
    `apps.purchase.services.public` etait vide de toute fonction de
    LECTURE jusqu'ici (seulement `open_purchase_incident`, une commande) —
    `logistics` en a besoin pour afficher une reference lisible sur
    `LogShipment.purchase_orders` (liste d'UUID nus, jamais de FK Django,
    regle de couplage n°1). Meme discipline que
    `sales.services.public.get_order_reference` : retourne une chaine vide,
    jamais une exception, si la commande n'existe pas."""
    order = PurOrder.objects.filter(id=order_id).first()
    return order.reference if order is not None else ""
