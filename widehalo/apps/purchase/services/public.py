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

from apps.catalog.services.public import get_conversion_factor, get_variant_base_uom_code
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.purchase.models import PurOrder, PurOrderLine, PurReceiptLine
from apps.purchase.services.cri import create_cri
from apps.purchase.services.requisitions import add_requisition_line, create_requisition

# Bloc F, F1 : commande fournisseur "en cours" = deja engagee et pas
# encore integralement receptionnee/close/annulee. Decision de cadrage
# (aucun precedent ne definissait cet ensemble avant ce sprint) :
# SENT/CONFIRMED/IN_TRANSIT/PARTIALLY_RECEIVED — jamais un brouillon
# non confirme (DRAFT/TO_VALIDATE/VALIDATED, pas encore un engagement
# ferme envers le fournisseur), jamais RECEIVED/INVOICED/CLOSED (plus
# rien a recevoir), jamais CANCELLED/IN_DISPUTE (approvisionnement
# compromis, ne doit pas etre compte comme un apport futur fiable).
_OPEN_ORDER_STATES = (
    PurOrder.STATE_SENT,
    PurOrder.STATE_CONFIRMED,
    PurOrder.STATE_IN_TRANSIT,
    PurOrder.STATE_PARTIALLY_RECEIVED,
)


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


def get_order_summary(order_id: Any) -> dict[str, Any] | None:
    """Gap B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué",
    cf. plan) : `financing` a besoin de plus qu'une simple référence
    (`get_order_reference` ci-dessus) pour ancrer la frise chronologique
    d'un dossier — son statut et ses dates. Retourne un dict primitif
    `{"id", "reference", "state", "date", "date_expected",
    "import_dossier_pending"}`, jamais l'objet `PurOrder` (règle de
    couplage n°1). Retourne `None`, jamais une exception, si la commande
    n'existe pas — même discipline que `get_order_reference` (qui
    retourne une chaîne vide dans ce cas, adaptée ici au type de retour)."""
    order = PurOrder.objects.filter(id=order_id).first()
    if order is None:
        return None
    return {
        "id": order.id,
        "reference": order.reference,
        "state": order.state,
        "date": order.date,
        "date_expected": order.date_expected,
        "import_dossier_pending": order.import_dossier_pending,
    }


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


def list_orders_for_partner(partner_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Gap PT5 du chantier "fiche partenaire a onglets par role" (cf.
    plan) : alimente l'onglet "Fournisseur (achat)" de la fiche
    partenaire avec les `PurOrder` de ce fournisseur — `partners` ne doit
    jamais importer `apps.purchase.models` (regle de couplage n1).

    Retourne des dicts primitifs `{"id", "reference", "date", "state",
    "total"}`, jamais l'objet `PurOrder`, tries par date decroissante
    (commande la plus recente en premier). Liste vide, jamais
    d'exception, si aucune commande ne correspond a ce `partner_id`."""
    orders = PurOrder.objects.filter(partner_id=partner_id).order_by("-date", "-id")[:limit]
    return [
        {
            "id": order.id,
            "reference": order.reference,
            "date": order.date,
            "state": order.state,
            "total": order.amount_total_mga,
        }
        for order in orders
    ]


def list_receipt_lines_for_warehouse(
    tenant: Tenant, *, updated_since: Any = None
) -> list[dict[str, Any]]:
    """Bloc Transverse, T2 (FOR-11, ferme ACH-10) : extrait les
    `PurReceiptLine` pour alimenter `apps.analytics.AnFactReception` —
    seule voie d'accès pour `analytics`, qui ne doit jamais importer
    `apps.purchase.models` (règle de couplage n°1).

    `updated_since` (datetime ou None) filtre sur `PurReceiptLine.
    updated_at` STRICTEMENT supérieur — même contrat exact que
    `stocks.services.public.list_moves_for_warehouse`. Renvoie des dicts
    primitifs, jamais l'objet `PurReceiptLine`. `date` = `created_at` (pas
    de champ date dédié sur `PurReceiptLine` — c'est un événement, créé
    exactement au moment de la réception, cf. docstring du modèle)."""
    qs = PurReceiptLine.objects.filter(order_line__order__tenant=tenant).select_related(
        "order_line", "order_line__order"
    )
    if updated_since is not None:
        qs = qs.filter(updated_at__gt=updated_since)
    return [
        {
            "receipt_line_id": line.id,
            "updated_at": line.updated_at,
            "date": line.created_at.date(),
            "order_reference": line.order_line.order.reference,
            "partner_id": line.order_line.order.partner_id,
            "variant_id": line.order_line.variant_id,
            "qty_received": line.qty_received,
            "uom": line.order_line.uom,
            "unit_price_mga": line.order_line.unit_price_mga,
            "quality_status": line.quality_status,
        }
        for line in qs
    ]


def get_open_order_qty(variant_id: Any) -> Decimal:
    """Bloc F, F1 : quantité restant à recevoir (`qty - qty_received`)
    sur les commandes fournisseur EN COURS (cf. `_OPEN_ORDER_STATES` ci-
    dessus pour la définition exacte) pour `variant_id`, convertie dans
    l'UNITÉ DE STOCK de la variante — `PurOrderLine.qty`/`uom` restent
    TOUJOURS exprimés dans l'unité d'ACHAT de la ligne (jamais
    contrainte à l'unité de stock, cf. docstring `PurOrderLine`), même
    conversion DÉCLARÉE que `stocks.services.public.
    receive_purchase_line` (B1, `catalog.services.public.
    get_conversion_factor`) — jamais un facteur deviné.

    Une ligne dont l'unité d'achat n'a pas de facteur de conversion
    déclaré vers l'unité de stock est ignorée (gap de configuration à
    la charge du tenant, même discipline que `receive_purchase_line` —
    jamais une estimation silencieuse à facteur 1). Retourne
    `Decimal(0)` si la variante elle-même est inconnue."""
    stock_uom_code = get_variant_base_uom_code(variant_id)
    if stock_uom_code is None:
        return Decimal(0)
    total = Decimal(0)
    lines = PurOrderLine.objects.filter(order__state__in=_OPEN_ORDER_STATES, variant_id=variant_id)
    for line in lines:
        remaining = line.qty - line.qty_received
        if remaining <= 0:
            continue
        factor = get_conversion_factor(from_uom_code=line.uom, to_uom_code=stock_uom_code)
        if factor is None:
            continue
        total += remaining * factor
    return total
