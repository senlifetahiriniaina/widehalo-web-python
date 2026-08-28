"""Contrat public de l'app `purchase` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Premier gap reellement expose, ajoute pour ST3 de `stocks` (RG-STK-4, cf.
plan) : `open_purchase_incident`, enveloppe fine de
`purchase.services.cri.create_cri` — consomme par
`apps.stocks.services.measurements.record_measurement` pour ouvrir
automatiquement un litige fournisseur quand un ecart de mesure depasse le
seuil parametrable. Remplace le "rien a exposer pour l'instant" de PU1.

Gap ajoute par le chantier de durcissement retroactif qui leve le stub
RG-SAL-3 "a acheter" de `sales.services.procurement` :
`create_requisition_line_from_source`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.purchase.models import PurOrder
from apps.purchase.services.cri import create_cri
from apps.purchase.services.requisitions import add_requisition_line, create_requisition


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


def create_requisition_line_from_source(
    tenant: Tenant,
    *,
    requester_user_id: Any,
    variant_id: Any,
    qty: Decimal,
    date_needed: dt.date,
    description: str = "",
) -> UUID | None:
    """Gap ajoute par le chantier de durcissement retroactif qui leve le
    stub RG-SAL-3 "a acheter" de `sales.services.procurement.
    qualify_and_process_order` (`apps.purchase` n'existait pas encore
    quand `sales` a ete construit, cf. plan). Enveloppe
    `services.requisitions.create_requisition`/`add_requisition_line`
    (deja construits PU1/PU2, aucune logique de demande d'achat dupliquee
    ici) : cree une VRAIE `PurRequisition` a UNE ligne, toujours en
    `draft` — jamais soumise/approuvee automatiquement (meme discipline
    "jamais d'auto-post" que `accounting.services.public.
    create_customer_invoice_from_source`/`create_supplier_invoice_from_
    source`).

    **Simplification assumee documentee** : une demande a une seule ligne
    est creee a CHAQUE appel, jamais reutilisee/regroupee avec une demande
    `draft` deja ouverte pour le meme `requester_user_id` ce jour — un
    tel regroupement supposerait une cle de regroupement metier (par
    fournisseur ? par date de besoin ?) que RG-SAL-3 ne fournit pas, et
    l'aurait rendu arbitraire. Meme choix "une demande simple par
    declenchement, tracable, jamais un regroupement invente" que
    `purchase.services.reordering.run_reordering` (RG-PUR-3).

    `requester_user_id` doit resoudre vers un `core.User` REEL
    (`PurRequisition.requester` est une FK obligatoire) — retourne `None`,
    jamais une exception, si aucun utilisateur ne correspond : c'est le
    mode d'echec realiste attendu d'un appelant `sales` (un `core.User`
    cote vente n'a pas necessairement de mapping valide cote achats).
    Retourne egalement `None` (jamais une exception) si `variant_id` ne
    correspond a aucune variante catalogue reelle — meme discipline,
    `add_requisition_line` exige une variante resolvable pour estimer son
    prix (`catalog.services.public.get_variant_price`).

    Retourne l'UUID de la `PurRequisitionLine` creee (PAS d'une
    `PurOrderLine` — le cycle demande -> RFQ -> commande reste une
    decision humaine/metier, volontairement hors perimetre de ce gap)."""
    requester = User.objects.filter(id=requester_user_id).first()
    if requester is None:
        return None

    try:
        with transaction.atomic():
            requisition = create_requisition(
                tenant=tenant,
                requester=requester,
                date_needed=date_needed,
                justification=description,
                source_document="sales.procurement",
            )
            line = add_requisition_line(
                requisition, variant_id=variant_id, description=description, qty=qty
            )
    except ObjectDoesNotExist:
        # `add_requisition_line` -> `catalog.services.public.get_variant_price`
        # leve `ProductVariant.DoesNotExist` (sous-classe d'`ObjectDoesNotExist`,
        # capturee ici generiquement pour ne jamais importer `apps.catalog.models`,
        # regle de couplage n1) si `variant_id` ne correspond a aucune variante
        # catalogue reelle.
        return None
    return line.id
