"""Contrat public de l'app `stocks` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Premier gap reellement expose, ajoute pour LOG5 de `logistics` (RG-LOG-7,
cf. plan) : `apply_landed_cost_to_valuation`, appele a la cloture d'un
dossier douanier pour repercuter les couts d'approche reels sur la
valorisation du stock deja receptionne — remplace le stub documente au
Lot 2 ("stocks n'existe pas encore") maintenant que le module est
construit.

Chantier de durcissement retroactif (levee des stubs `sales`/`purchase`
saisis avant que `stocks` existe) : `check_and_reserve_stock` et
`get_available_stock_qty`, consommes respectivement par
`sales.services.procurement.qualify_and_process_order` (branche "sur
stock" de RG-SAL-3) et `purchase.services.reordering.run_reordering`
(RG-PUR-3)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.stocks.models import StkLocation, StkPicking, StkQuant, StkReservation, StkValuationLayer
from apps.stocks.services.pickings import add_picking_line, create_picking, mark_picking_ready, validate_picking
from apps.stocks.services.quants import available_qty
from apps.stocks.services.reservations import release_reservation, reserve_stock

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def apply_landed_cost_to_valuation(variant_id: Any, *, additional_cost_mga: Decimal) -> bool:
    """RG-LOG-7 : repartit un cout d'importation (deja comptabilise via
    `accounting.services.public.create_landed_cost_batch_from_source`, cet
    appel ne concerne QUE le cote stock) sur les couches de valorisation
    ACTIVES (`remaining_qty > 0`) de cette variante, au prorata de leur
    `remaining_qty` — une REVALORISATION du stock deja receptionne, jamais
    un nouveau mouvement physique : RG-STK-1 (double entree stricte) ne
    porte que sur les mouvements de quantite, pas sur la correction d'un
    cout d'entree deja constate. Documente comme simplification assumee :
    la repartition est purement proportionnelle a la quantite restante,
    pas ponderee par un autre critere (poids, valeur d'origine...).

    Retourne `False`, jamais une exception, si la variante n'a aucune
    couche de valorisation active — rien a revaloriser (cas normal, pas
    une erreur, meme discipline que les autres gaps `services.public` de
    ce depot)."""
    layers = list(StkValuationLayer.objects.filter(variant_id=variant_id, remaining_qty__gt=0))
    total_remaining_qty = sum((layer.remaining_qty for layer in layers), Decimal(0))
    if not layers or total_remaining_qty <= 0:
        return False

    for layer in layers:
        share = (layer.remaining_qty / total_remaining_qty) * additional_cost_mga
        layer.remaining_value_mga += share
        layer.value_mga += share
        if layer.qty:
            layer.unit_cost_mga = layer.value_mga / layer.qty
        layer.save(update_fields=["remaining_value_mga", "value_mga", "unit_cost_mga"])
    return True


def check_and_reserve_stock(
    tenant: Tenant,
    *,
    variant_id: Any,
    qty: Decimal,
    date: dt.date,
    source_object: models.Model | None = None,
) -> UUID | None:
    """Gap ajoute pour lever le stub RG-SAL-3 "sur stock" de
    `sales.services.procurement.qualify_and_process_order` (chantier de
    durcissement retroactif, cf. docstring de module) : un appelant externe
    ne connait qu'un `variant_id` (jamais un `StkQuant` precis, qui reste
    un detail d'implementation interne a `stocks`) — cette fonction resout
    UN quant capable de couvrir `qty` a lui seul, puis delegue a
    `services.reservations.reserve_stock` (deja construit ST5, aucune
    logique de reservation dupliquee ici).

    **Simplification assumee documentee** (meme discipline que
    `apply_landed_cost_to_valuation` ci-dessus) : le quant candidat est le
    PREMIER (`order_by("id")`, ordre de creation, deterministe) dont la
    disponibilite (`qty - qty_reserved`, memes emplacements INTERNES
    uniquement que `services.quants.available_qty`) couvre `qty` a lui
    seul. Aucun fractionnement d'une reservation sur plusieurs
    quants/emplacements n'est tente — une variante avec 3 quants de 10
    chacun ne peut pas honorer une demande de 15 via cette fonction, meme
    si le total agrege (30) suffirait. Ce choix privilegie la simplicite et
    la tracabilite (une reservation = un quant = un emplacement physique
    unique, jamais une reservation eclatee dont un appelant devrait
    recomposer l'origine) au prix d'un rejet plus frequent que necessaire
    dans un entrepot tres fragmente — jamais l'inverse (jamais une
    sur-reservation, jamais un faux positif).

    Retourne l'UUID de la `StkReservation` creee, ou `None` (jamais une
    exception) si aucun quant unique ne peut couvrir `qty` — cas normal
    ("stock insuffisant pour reserver en un bloc"), pas une erreur."""
    quant = (
        StkQuant.objects.filter(
            tenant=tenant, variant_id=variant_id, location__type=StkLocation.TYPE_INTERNE
        )
        .annotate(available=F("qty") - F("qty_reserved"))
        .filter(available__gte=qty)
        .order_by("id")
        .first()
    )
    if quant is None:
        return None
    reservation = reserve_stock(
        tenant=tenant, quant=quant, qty=qty, date=date, source_object=source_object
    )
    return reservation.id


@transaction.atomic
def deliver_reserved_stock(
    tenant: Tenant,
    *,
    reservation_id: UUID,
    date: dt.date,
    source_document: str = "",
    operator: User | None = None,
) -> UUID:
    """Gap ajoute pour lever le dernier stub retroactif reel de la chaine
    commerciale (audit `docs/audit/2026-09-cahier-des-charges-v3-audit.md`,
    §6/§8) : `sales.services.orders.mark_delivered` recopiait jusqu'ici
    `qty_delivered = qty` SANS jamais toucher `stocks`, avec un commentaire
    date de l'epoque (S2) ou ce module n'existait pas encore — devenu
    obsolete puisque `stocks` est aujourd'hui pleinement construit
    (`check_and_reserve_stock` ci-dessus reservait deja le stock a la
    confirmation de commande, mais rien ne consommait jamais cette
    reservation a la livraison).

    Consomme une `StkReservation` ACTIVE (creee par
    `check_and_reserve_stock`) en une VRAIE sortie de stock : cree un
    `StkPicking` de type "sortie" avec une seule ligne, le fait suivre son
    cycle de vie complet (`draft -> ready -> done`, moteur ST2/ST4
    reutilise integralement via `services.pickings`/`services.moves` —
    aucune logique de mouvement dupliquee ici), PUIS libere la reservation
    (RG-STK-8 : liberer `qty_reserved` est une action distincte de
    l'execution physique du mouvement, cf. `services.reservations`).
    `@transaction.atomic` : soit la livraison ET la liberation de la
    reservation reussissent ensemble, soit aucune des deux n'est
    persistee — jamais un picking valide avec une reservation restee
    active (double-comptage du disponible) ni l'inverse.

    Refuse (`ValidationError` i18n) si aucun emplacement virtuel `client`
    n'existe pour l'entrepot de la reservation (meme garde exacte que
    `services.returns.process_return`) — la reservation reste alors
    active, a charge de l'appelant de la traiter manuellement.

    Retourne l'UUID du `StkPicking` cree (bon de livraison)."""
    reservation = StkReservation.objects.select_related(
        "quant", "quant__location", "quant__location__warehouse", "quant__lot"
    ).get(tenant=tenant, pk=reservation_id, state=StkReservation.STATE_ACTIVE)
    quant = reservation.quant
    location_from = quant.location

    client_location = StkLocation.objects.filter(
        tenant=tenant, warehouse=location_from.warehouse, type=StkLocation.TYPE_CLIENT
    ).first()
    if client_location is None:
        raise ValidationError(
            _(
                "Aucun emplacement virtuel client trouvé pour l'entrepôt de la "
                "réservation — livraison impossible."
            )
        )

    picking = create_picking(
        tenant=tenant,
        type=StkPicking.TYPE_SORTIE,
        location_from=location_from,
        location_to=client_location,
        date_scheduled=date,
        source_document=source_document,
    )
    add_picking_line(
        picking,
        variant_id=quant.variant_id,
        qty=reservation.qty,
        uom=quant.uom,
        unit_cost_mga=quant.unit_cost_mga,
        lot=quant.lot,
        operator=operator,
    )
    mark_picking_ready(picking)
    validate_picking(picking, date_done=date)
    release_reservation(reservation)
    return picking.id


def get_available_stock_qty(variant_id: Any) -> Decimal:
    """Gap ajoute pour lever le stub RG-PUR-3 de
    `purchase.services.reordering.run_reordering` (chantier de
    durcissement retroactif, cf. docstring de module) : delegation PURE a
    `services.quants.available_qty` (deja `qty - qty_reserved` agrege sur
    les emplacements INTERNES uniquement — aucun recalcul duplique ici),
    meme patron que `services.reservations.available_to_sell`."""
    return available_qty(variant_id)


def decide_stock_import_qualification(
    approval_request_id: UUID, decided_by: User, *, approved: bool, comment: str = ""
) -> None:
    """Enveloppe publique de `apps.stocks.services.stock_import.
    decide_qualification` — seule surface autorisee pour l'ecran generique
    "Mes validations en attente" (`apps.core.api_workflow.decide_approval`,
    chantier RG-QUALIF) qui doit repercuter la decision sur le statut du
    `StkImportRow`, en plus de la decision `ApprovalRequest` elle-meme
    (deja geree generiquement par `apps.core.services.approvals.decide`)."""
    from apps.core.models.workflow import ApprovalRequest as _ApprovalRequest
    from apps.stocks.services.stock_import import decide_qualification

    approval_request = _ApprovalRequest.objects.get(id=approval_request_id)
    decide_qualification(approval_request, decided_by, approved=approved, comment=comment)


# --------------------------------------------------------------------------
# A2 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) : premiere
# consommation de cette surface par `mrp` — jusqu'ici `mrp` ne creait aucun
# `StkMove` (cf. docstring de
# `apps.stocks.services.consistency.production_consistency_report`, qui
# documente explicitement ce manque pour RG-STK-6). Les fonctions
# ci-dessous ferment ce manque pour le seul cas "reception de la production
# d'un ordre de transformation", sans reconstruire une integration
# MRP/stocks complete (reservation/consommation des composants reste hors
# perimetre A2, deja couverte cote utilisateur par le flux de picking
# existant).
# --------------------------------------------------------------------------

from apps.stocks.models import StkLot, StkMove  # noqa: E402
from apps.stocks.services.genealogy import genealogy_tree, record_consumption  # noqa: E402
from apps.stocks.services.moves import create_move, validate_move  # noqa: E402


def list_locations(tenant: Tenant) -> list[dict[str, Any]]:
    """Primitives uniquement (jamais `StkLocation`) pour alimenter un
    sélecteur d'emplacement côté appelant (ex. formulaire de clôture d'un
    ordre de transformation `mrp`)."""
    return [
        {"id": location.id, "code": location.code, "name": location.name, "type": location.type}
        for location in StkLocation.objects.filter(tenant=tenant, is_active=True).order_by("code")
    ]


def get_or_create_lot(
    *,
    tenant: Tenant,
    variant_id: Any,
    name: str,
    date_production: dt.date | None = None,
    date_expiry: dt.date | None = None,
) -> UUID:
    """Résout un lot existant par `(tenant, variant_id, name)`
    (`UniqueConstraint` déjà en place sur `StkLot`) ou le crée. Ne met
    jamais à jour un lot déjà existant (un lot est un identifiant, pas un
    enregistrement mutable au fil des appels) — les dates ne sont
    appliquées qu'à la création."""
    lot, _created = StkLot.objects.get_or_create(
        tenant=tenant,
        variant_id=variant_id,
        name=name,
        defaults={"date_production": date_production, "date_expiry": date_expiry},
    )
    lot_id: UUID = lot.id
    return lot_id


def receive_production_output(
    *,
    tenant: Tenant,
    variant_id: Any,
    qty: Decimal,
    location_to_id: Any,
    date: dt.date,
    source_document: str,
    lot_name: str = "",
    unit_cost_mga: Decimal = Decimal(0),
) -> UUID:
    """Réception en stock de la production d'un ordre de transformation
    (`mrp.MrpOrder`) : crée+valide un `StkMove` `production_in`, comblant
    le manque documenté par RG-STK-6 (jusqu'à A2, `mrp` ne créait aucun
    mouvement — `production_consistency_report` ne trouvait donc jamais de
    quantité réellement entrée en stock pour un ordre clos). `location_from`
    est toujours l'emplacement virtuel `TYPE_PRODUCTION` du même entrepôt
    que `location_to` (créé s'il n'existe pas encore) — même convention
    que les autres mouvements virtuel->interne du module (réception
    fournisseur, retour client)."""
    location_to = StkLocation.objects.get(tenant=tenant, id=location_to_id)
    location_from, _created = StkLocation.objects.get_or_create(
        tenant=tenant,
        warehouse=location_to.warehouse,
        type=StkLocation.TYPE_PRODUCTION,
        defaults={"code": f"{location_to.warehouse.code}-PROD", "name": "Production (virtuel)"},
    )
    lot = None
    if lot_name:
        lot_id = get_or_create_lot(tenant=tenant, variant_id=variant_id, name=lot_name)
        lot = StkLot.objects.get(id=lot_id)
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="",
        location_from=location_from,
        location_to=location_to,
        date=date,
        move_type=StkMove.TYPE_PRODUCTION_IN,
        source_document=source_document,
        unit_cost_mga=unit_cost_mga,
        lot=lot,
    )
    validate_move(move)
    move_id: UUID = move.id
    return move_id


def record_lot_genealogy(
    *,
    tenant: Tenant,
    parent_variant_id: Any,
    parent_lot_name: str,
    child_variant_id: Any,
    child_lot_name: str,
    qty: Decimal,
    source_document: str = "",
) -> UUID | None:
    """Lie un lot parent (matière/composant consommé) à un lot enfant
    (sortie de transformation), pour la traçabilité amont/aval A2/A3.
    Crée les deux lots s'ils n'existent pas déjà (discipline "jamais de
    faux positif" : un appelant qui fournit un nom de lot inédit doit voir
    le lien créé, pas silencieusement ignoré). Retourne `None` uniquement
    si `qty <= 0` (rien à enregistrer), jamais une exception — l'appelant
    (`mrp`) ne doit pas avoir à gérer un cas d'erreur pour une entrée de
    consommation simplement vide/non renseignée."""
    if qty <= 0:
        return None
    parent_id = get_or_create_lot(tenant=tenant, variant_id=parent_variant_id, name=parent_lot_name)
    child_id = get_or_create_lot(tenant=tenant, variant_id=child_variant_id, name=child_lot_name)
    link = record_consumption(
        tenant=tenant,
        parent_lot=StkLot.objects.get(id=parent_id),
        child_lot=StkLot.objects.get(id=child_id),
        qty=qty,
        source_document=source_document,
    )
    link_id: UUID = link.id
    return link_id


def lot_genealogy_tree(*, tenant: Tenant, variant_id: Any, name: str) -> dict[str, Any] | None:
    """Arbre de traçabilité amont/aval du lot `(tenant, variant_id, name)`
    — `None`, jamais une exception, si ce lot n'existe pas (ex. l'ordre de
    transformation n'a pas encore été clôturé avec un nom de lot de
    sortie)."""
    lot = StkLot.objects.filter(tenant=tenant, variant_id=variant_id, name=name).first()
    if lot is None:
        return None
    return genealogy_tree(lot)
