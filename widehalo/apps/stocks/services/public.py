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
from django.db.models import F, Sum
from django.utils.translation import gettext as _

from apps.catalog.services.public import (
    get_conversion_factor,
    get_variant_base_uom_code,
    requires_certificate_of_analysis,
)
from apps.core.models.user import User
from apps.stocks.models import (
    StkLocation,
    StkPicking,
    StkQuant,
    StkReservation,
    StkValuationLayer,
    StkWarehouse,
)
from apps.stocks.services.pickings import (
    add_picking_line,
    create_picking,
    mark_picking_ready,
    validate_picking,
)
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


def get_variant_unit_cost(tenant: Tenant, variant_id: Any) -> Decimal | None:
    """Bloc C, C3 (RG-MRP-6/PRD-9) : coût unitaire courant CUMP d'une
    variante — moyenne pondérée des couches `StkValuationLayer` ACTIVES
    (`remaining_qty > 0`), même agrégat que `_consume_average_cost`
    (`services.moves`) mais en LECTURE PURE (aucune couche modifiée).
    Consommée par `mrp.services.orders.close_order` pour assembler
    `component_unit_costs` sans que l'appelant ait à connaître le détail
    interne de `stocks` (couches, quants).

    Retourne `None`, jamais une exception, si la variante n'a aucune
    couche active — même discipline que les autres gaps `services.public`
    de ce fichier (`check_and_reserve_stock` ci-dessous, par ex.)."""
    layers = StkValuationLayer.objects.filter(
        tenant=tenant, variant_id=variant_id, remaining_qty__gt=0
    )
    total_qty = Decimal(0)
    total_value = Decimal(0)
    for layer in layers:
        total_qty += layer.remaining_qty
        total_value += layer.remaining_value_mga
    if total_qty <= 0:
        return None
    return total_value / total_qty


def get_variant_unit_cost_at_date(
    tenant: Tenant, variant_id: Any, *, at_date: dt.date
) -> Decimal | None:
    """CUMP d'une variante A UNE DATE PASSEE (PRD-9, L12-2).

    `get_variant_unit_cost` ci-dessus ne sait donner que le CUMP COURANT :
    il lit les couches actives, dont `remaining_qty`/`remaining_value_mga`
    sont un etat ecrase a chaque sortie. Aucune couche ne conserve
    l'historique date de sa consommation, donc aucune lecture de couche ne
    peut restituer un cout passe.

    PRD-9 exige pourtant le CUMP « a la date d'effet » de chaque
    consommation : sur un ordre dont les consommations s'etalent et dont le
    CUMP bouge entre-temps, le cout de cloture calcule au CUMP courant est
    faux, parfois de beaucoup. Ce gap expose donc le rejeu
    (`services.valuation_replay.replay_unit_cost`), qui reconstruit les
    couches en memoire depuis les `StkMove`.

    **Cout d'appel a connaitre** : le rejeu relit tous les mouvements du
    variant jusqu'a `at_date`. C'est acceptable a la cloture d'un ordre de
    fabrication (une fois par ordre, quelques composants), ce n'est PAS un
    substitut a `get_variant_unit_cost` sur un chemin chaud.

    Retourne `None`, jamais une exception, si aucun stock n'existait a
    cette date — un zero serait un chiffre faux la ou il n'y a pas de cout
    a produire, meme discipline que les autres gaps de ce fichier."""
    from apps.stocks.services.valuation_replay import replay_unit_cost

    return replay_unit_cost(tenant, variant_id=variant_id, at_date=at_date)


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


def release_stock_reservation(tenant: Tenant, *, reservation_id: UUID, reason: str = "") -> bool:
    """Bloc C, C1 : enveloppe fine pour libérer une réservation depuis un
    autre module (`mrp`, à la clôture/annulation d'un `MrpOrder`) sans
    jamais importer `apps.stocks.models.StkReservation` (règle de
    couplage n°1) — `services.reservations.release_reservation` prend
    une INSTANCE, pas un UUID, et aucune fonction `services.public`
    n'existait jusqu'ici pour ce besoin cross-app.

    Retourne `False`, jamais une exception, si la réservation n'existe
    pas ou n'est plus active — idempotent, sûr à appeler plusieurs fois
    (même discipline que les autres gaps `services.public` de ce
    fichier : jamais une erreur pour un état déjà atteint)."""
    reservation = StkReservation.objects.filter(
        tenant=tenant, id=reservation_id, state=StkReservation.STATE_ACTIVE
    ).first()
    if reservation is None:
        return False
    release_reservation(reservation, reason=reason)
    return True


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


@transaction.atomic
def sell_from_stock(
    tenant: Tenant,
    *,
    variant_id: Any,
    qty: Decimal,
    warehouse_id: Any,
    date: dt.date,
    source_document: str = "",
    operator: User | None = None,
) -> UUID | None:
    """Gap ajoute pour le module `pos` (cahier §13.5, POS distribution) :
    a la difference de la chaine `check_and_reserve_stock` ->
    `deliver_reserved_stock` de `sales` (reservation PUIS livraison, deux
    temps espaces dans le workflow devis/commande), le point de vente
    encaisse et sort le stock en UN SEUL GESTE synchrone — pas de
    reservation prealable, jamais un `StkReservation` cree ici.

    Meme simplification assumee que `check_and_reserve_stock` (cf. sa
    docstring) : resout un emplacement interne UNIQUE de l'entrepot
    `warehouse_id` capable de couvrir `qty` a lui seul (aucun
    fractionnement sur plusieurs emplacements). Cree+valide directement un
    `StkPicking` de sortie (`draft -> ready -> done`, meme moteur ST2/ST4
    reutilise que `deliver_reserved_stock`) vers l'emplacement virtuel
    client de cet entrepot.

    Retourne `None`, jamais une exception, si l'entrepot n'existe pas, si
    aucun emplacement/quant unique ne peut couvrir `qty` (stock
    insuffisant — cas normal, a charge de l'appelant `pos` de refuser la
    vente), ou si aucun emplacement virtuel client n'existe pour cet
    entrepot (meme discipline "gap de configuration a la charge du
    tenant" que le reste de ce module). Retourne l'UUID du `StkPicking`
    cree (ticket de caisse valant bon de sortie) sinon."""
    warehouse = StkWarehouse.objects.filter(tenant=tenant, id=warehouse_id).first()
    if warehouse is None:
        return None

    quant = (
        StkQuant.objects.filter(
            tenant=tenant,
            variant_id=variant_id,
            location__type=StkLocation.TYPE_INTERNE,
            location__warehouse=warehouse,
        )
        .annotate(available=F("qty") - F("qty_reserved"))
        .filter(available__gte=qty)
        .order_by("id")
        .first()
    )
    if quant is None:
        return None

    client_location = StkLocation.objects.filter(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT
    ).first()
    if client_location is None:
        return None

    picking = create_picking(
        tenant=tenant,
        type=StkPicking.TYPE_SORTIE,
        location_from=quant.location,
        location_to=client_location,
        date_scheduled=date,
        source_document=source_document,
    )
    add_picking_line(
        picking,
        variant_id=quant.variant_id,
        qty=qty,
        uom=quant.uom,
        unit_cost_mga=quant.unit_cost_mga,
        lot=quant.lot,
        # POS-3 (L6) : nature `vente_comptoir`, et non la `livraison` que
        # `_DEFAULT_MOVE_TYPE_BY_PICKING_TYPE` deduirait d'un picking de
        # sortie. La nature existait depuis la Phase 3 SANS AUCUN
        # PRODUCTEUR — sa propre declaration le disait : « le cablage reel
        # d'`apps.pos` sur cette nouvelle valeur est un chantier distinct ».
        # Une vente au comptoir n'est pas une expedition : elle ne suit
        # aucun bon de livraison, et les confondre rendait toute analyse des
        # sorties par nature (cahier §9) muette sur la caisse.
        move_type=StkMove.TYPE_VENTE_COMPTOIR,
        operator=operator,
    )
    mark_picking_ready(picking)
    validate_picking(picking, date_done=date)
    picking_id: UUID = picking.id
    return picking_id


@transaction.atomic
def receive_pos_return(
    tenant: Tenant,
    *,
    variant_id: Any,
    qty: Decimal,
    warehouse_id: Any,
    date: dt.date,
    source_document: str = "",
    operator: User | None = None,
) -> UUID | None:
    """Pendant retour de `sell_from_stock` ci-dessus, pour un retour/avoir
    POS (cahier §13.5, "Retour, échange, avoir") — remet `qty` en stock,
    de l'emplacement virtuel client vers le PREMIER emplacement interne de
    l'entrepot (simplification assumee et disclosee : le point de vente ne
    trace pas de quel emplacement interne precis la marchandise retournee
    provenait a l'origine, un retour rejoint donc l'emplacement interne
    "principal" de l'entrepot plutot qu'un emplacement reconstitue —
    meme esprit que `apply_landed_cost_to_valuation`, qui documente
    egalement une repartition simplifiee faute d'un signal plus precis).

    Retourne `None`, jamais une exception, si l'entrepot n'existe pas, si
    aucun emplacement interne n'existe pour cet entrepot, ou si aucun
    emplacement virtuel client n'existe (memes gardes de configuration que
    `sell_from_stock`). Retourne l'UUID du `StkPicking` d'entree cree
    sinon."""
    warehouse = StkWarehouse.objects.filter(tenant=tenant, id=warehouse_id).first()
    if warehouse is None:
        return None

    internal_location = StkLocation.objects.filter(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_INTERNE
    ).first()
    if internal_location is None:
        return None

    client_location = StkLocation.objects.filter(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_CLIENT
    ).first()
    if client_location is None:
        return None

    picking = create_picking(
        tenant=tenant,
        type=StkPicking.TYPE_ENTREE,
        location_from=client_location,
        location_to=internal_location,
        date_scheduled=date,
        source_document=source_document,
    )
    add_picking_line(
        picking,
        variant_id=variant_id,
        qty=qty,
        uom="",
        operator=operator,
    )
    mark_picking_ready(picking)
    validate_picking(picking, date_done=date)
    picking_id: UUID = picking.id
    return picking_id


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

from apps.stocks.models import StkLot, StkMove, StkQualityState  # noqa: E402
from apps.stocks.services.genealogy import genealogy_tree, record_consumption  # noqa: E402
from apps.stocks.services.moves import create_move, validate_move  # noqa: E402
from apps.stocks.services.quality import (  # noqa: E402
    set_quality_state as _set_quality_state,
)
from apps.stocks.services.quants import get_quant  # noqa: E402


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
    certificate_document_id: UUID | None = None,
) -> UUID:
    """Résout un lot existant par `(tenant, variant_id, name)`
    (`UniqueConstraint` déjà en place sur `StkLot`) ou le crée. Ne met
    jamais à jour un lot déjà existant (un lot est un identifiant, pas un
    enregistrement mutable au fil des appels) — les dates ET le
    certificat (Bloc D, D2/QUA-8) ne sont appliqués qu'à la création."""
    lot, _created = StkLot.objects.get_or_create(
        tenant=tenant,
        variant_id=variant_id,
        name=name,
        defaults={
            "date_production": date_production,
            "date_expiry": date_expiry,
            "certificate_document_id": certificate_document_id,
        },
    )
    lot_id: UUID = lot.id
    return lot_id


def get_lot_certificate_document_id(*, tenant: Tenant, variant_id: Any, name: str) -> UUID | None:
    """Bloc D, D2 (QUA-8) : lecture pure de `StkLot.certificate_document_id`
    pour un appelant cross-app (`apps.quality`, reporting/tableau de bord
    — jamais le mécanisme de blocage lui-même, qui vit entièrement dans
    `receive_purchase_line` ci-dessous). Résout le lot par
    `(tenant, variant_id, name)`, même convention que
    `lot_genealogy_tree`. `None`, jamais une exception, si le lot
    n'existe pas ou n'a aucun certificat rattaché."""
    lot = StkLot.objects.filter(tenant=tenant, variant_id=variant_id, name=name).first()
    if lot is None:
        return None
    return lot.certificate_document_id


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


def scrap_from_stock(
    *,
    tenant: Tenant,
    variant_id: Any,
    qty: Decimal,
    warehouse_id: Any,
    date: dt.date,
    source_document: str,
    unit_cost_mga: Decimal = Decimal(0),
) -> UUID | None:
    """Mouvement de mise au rebut (PRD-6, L12-4) — cree+valide un `StkMove`
    `TYPE_REBUT` vers l'emplacement rebut de l'entrepot.

    **Comble une promesse restee lettre morte.**
    `mrp.services.interventions.declare_scrap` annoncait que le mouvement
    vers l'emplacement rebut « sera branche une fois ces modules
    disponibles ». Ils le sont depuis A2 — `mrp` consomme deja
    `receive_production_output` — mais AUCUN `StkMove.TYPE_REBUT` n'etait
    produit par quoi que ce soit. Le critere PRD-6 (« le taux de conformite
    au premier passage est recalculable a l'identique depuis les
    mouvements ») etait donc litteralement infaisable : le rebut n'atteignait
    jamais le stock.

    **Meme convention d'emplacements que `receive_production_output`**
    ci-dessus : `location_to` est l'emplacement `TYPE_REBUT` de l'entrepot
    (cree s'il n'existe pas), `location_from` l'emplacement virtuel
    `TYPE_PRODUCTION` du meme entrepot. La piece rejetee suit exactement le
    chemin de la bonne, vers une autre benne — c'est cette symetrie qui
    justifie de ne pas inventer une troisieme convention.

    **Ce mouvement ne deplace aucun montant, et c'est voulu.**
    `unit_cost_mga` vaut zero par defaut, donc `value_delta` est nul, donc
    `validate_move` ne poste AUCUNE ecriture comptable (sa garde
    `value_delta != 0`). Brancher le rebut rend la quantite tracable ; il ne
    change ni la valeur de stock ni le solde du compte de stock — verifie
    par `test_prd6_scrap_movements.py` contre `replay_stock_value`
    (L12-1/STK-12) plutot qu'affirme ici.

    **Reserve a connaitre.** La branche `virtuel -> interne` de
    `validate_move` cree une `StkValuationLayer` INCONDITIONNELLEMENT, meme
    a valeur nulle : une couche a cout zero et quantite positive dilue le
    CUMP du variant. C'est sans effet aujourd'hui — `mrp.services.
    transformation.finish_transformation_order` recoit deja sa production a
    cout zero (`receive_production_output`, defaut a 0), donc le pool du
    produit fini est uniformement nul. Le jour ou la production entrera a
    son cout reel, le rebut le diluerait. « La production entre en stock a
    cout zero » est un ecart en soi, signale comme chantier separe plutot
    que corrige au passage ici — meme traitement que la reserve `scan.py`
    documentee dans `services/valuation_replay.py`.

    Retourne `None`, jamais une exception, si `qty <= 0` (rien a tracer) ou
    si l'entrepot est introuvable — meme discipline « aucun gap ne fait
    echouer le module appelant » que le reste de ce fichier."""
    if qty is None or qty <= 0:
        return None
    warehouse = StkWarehouse.objects.filter(tenant=tenant, id=warehouse_id).first()
    if warehouse is None:
        return None

    location_to, _created_to = StkLocation.objects.get_or_create(
        tenant=tenant,
        warehouse=warehouse,
        type=StkLocation.TYPE_REBUT,
        defaults={
            "code": f"{warehouse.code}-REBUT",
            "name": "Rebut",
            # Champ redondant avec `type == TYPE_REBUT` mais explicitement
            # liste dans le CDC (§5.8) — pose ici pour que l'emplacement cree
            # automatiquement soit indiscernable d'un emplacement configure a
            # la main sur l'ecran (`views.py`, case « Rebut »).
            "is_scrap": True,
        },
    )
    location_from, _created_from = StkLocation.objects.get_or_create(
        tenant=tenant,
        warehouse=warehouse,
        type=StkLocation.TYPE_PRODUCTION,
        defaults={"code": f"{warehouse.code}-PROD", "name": "Production (virtuel)"},
    )
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="",
        location_from=location_from,
        location_to=location_to,
        date=date,
        move_type=StkMove.TYPE_REBUT,
        source_document=source_document,
        unit_cost_mga=unit_cost_mga,
    )
    validate_move(move)
    move_id: UUID = move.id
    return move_id


def list_scrap_quantities_by_source(
    tenant: Tenant, *, source_documents: list[str]
) -> dict[str, Decimal]:
    """Quantites mises au rebut, agregees PAR `source_document` (PRD-6).

    Renvoie un dictionnaire de primitives, jamais des `StkMove` (regle de
    couplage n1) — `mrp` recalcule son taux de conformite au premier
    passage depuis ces quantites sans jamais atteindre les modeles de
    `stocks`.

    **L'agregation par `source_document` est le coeur du critere, pas un
    detail d'implementation.** Le FPY somme `qty_done`/`qty_rejected` sur
    TOUS les ordres de travail d'un ordre de fabrication : sur une gamme a
    trois postes, la meme piece physique est comptee trois fois. Un
    recalcul qui sommerait naivement tous les mouvements de rebut d'un
    ordre ne retomberait donc jamais sur le FPY. Chaque mouvement porte son
    poste dans `source_document` (`{reference}/WO{sequence}`, cf.
    `mrp.services.orders.done_work_order`), et le rebut declare par
    intervention porte un marqueur distinct (`{reference}/SCRAP`) pour que
    les deux natures ne se melangent jamais.

    Une cle absente du resultat signifie « aucun mouvement pour ce
    document » — l'appelant lit un zero, pas un `KeyError`, en passant par
    `.get(..., Decimal(0))`."""
    if not source_documents:
        return {}
    rows = (
        StkMove.objects.filter(
            tenant=tenant,
            move_type=StkMove.TYPE_REBUT,
            state=StkMove.STATE_DONE,
            source_document__in=source_documents,
        )
        .values("source_document")
        .annotate(total=Sum("qty"))
    )
    return {row["source_document"]: row["total"] or Decimal(0) for row in rows}


def receive_purchase_line(
    *,
    tenant: Tenant,
    variant_id: Any,
    qty: Decimal,
    uom: str,
    warehouse_id: Any,
    date: dt.date,
    source_document: str,
    unit_cost_mga: Decimal = Decimal(0),
    lot_name: str = "",
    date_production: dt.date | None = None,
    date_expiry: dt.date | None = None,
    certificate_document_id: UUID | None = None,
    operator: User | None = None,
) -> UUID | None:
    """Réception d'achat (`purchase.services.receiving.receive_order_line`)
    en un VRAI mouvement de stock — ferme le manque documenté par l'audit
    Phase 3 (§12.1 : « aucun module ne tient son propre compteur ») :
    jusqu'ici `receive_order_line` incrémentait `PurOrderLine.qty_received`
    sans jamais appeler `stocks`, deux comptabilités de quantité
    coexistaient et divergeaient silencieusement. Même patron que
    `receive_production_output` ci-dessus pour l'emplacement virtuel
    source (`TYPE_FOURNISSEUR`, créé au premier appel par entrepôt, comme
    `TYPE_PRODUCTION`) ; même simplification assumée que `sell_from_stock`/
    `receive_pos_return` pour l'emplacement interne de destination — le
    PREMIER emplacement interne de l'entrepôt, faute d'un rangement
    précis choisi à la réception dans le périmètre actuel de `purchase`
    (sélection fine de l'emplacement et date d'effet distincte de la date
    de saisie restent hors périmètre de ce chantier — cf. plan Phase 3,
    blocs A/B en Vague 2).

    B1 (Phase 3 §12.2/§14, cahier ACH-3) : `uom` (l'unité d'achat saisie
    sur la ligne de commande, `PurOrderLine.uom`, texte libre) est
    convertie vers l'unité de stock du produit (`catalog.services.public.
    get_variant_base_uom_code`) AVANT la création du `StkMove` — le
    mouvement de stock est ainsi TOUJOURS enregistré dans l'unité de
    stock, jamais dans l'unité d'achat, conformément au CDC. Le facteur de
    conversion est résolu via `catalog.services.public.
    get_conversion_factor` (DÉCLARÉ par le tenant, `catalog.
    UnitConversion` — jamais deviné, cf. sa docstring : « une conversion à
    facteur variable est interdite »). Ne tente une conversion QUE si les
    deux conditions suivantes sont réunies : `uom` est renseigné (une
    unité d'achat vide n'a rien à convertir) ET diffère réellement de
    l'unité de stock résolue. Si l'unité de stock du produit ne peut pas
    être résolue (variante inconnue du catalogue — cas courant des
    `variant_id` opaques non rattachés à un `catalog.ProductVariant` réel,
    ex. fixtures de test), AUCUNE conversion n'est tentée : la quantité et
    l'unité saisies sont utilisées telles quelles, même comportement
    qu'avant B1 — cohérent avec la discipline "gap de configuration à la
    charge du tenant" déjà établie ci-dessous pour l'entrepôt/emplacement.

    Retourne `None`, jamais une exception, si l'entrepôt de la commande
    n'est pas renseigné ou n'a aucun emplacement interne, OU si `uom`
    diffère de l'unité de stock résolue mais qu'AUCUNE `UnitConversion`
    n'est déclarée dans ce sens précis — même discipline "gap de
    configuration à la charge du tenant" que `sell_from_stock`/
    `receive_pos_return` ci-dessus ; à charge de l'appelant
    (`receive_order_line`) de refuser la réception plutôt que de laisser
    la quantité d'achat diverger silencieusement du stock physique (dans
    l'unité déclarée ou dans l'unité de stock réelle).

    Bloc D, D2 (QUA-8) : si l'article (`catalog.services.public.
    requires_certificate_of_analysis`) exige un certificat d'analyse,
    lève DIRECTEMENT `ValidationError` (contrairement aux gaps de
    configuration ci-dessus, qui restent des `None` silencieux) — soit si
    aucun `lot_name` n'est fourni (impossible de rattacher un certificat
    sans lot), soit si le lot résolu n'a aucun `certificate_document_id`
    (ni fourni à cet appel, ni déjà présent sur un lot existant). C'est un
    contrôle métier RÉEL déjà configuré par le tenant, pas un gap de
    configuration — un `None` silencieux, multiplexé avec les autres
    causes ci-dessus, empêcherait l'appelant de produire un message
    distinct et compréhensible."""
    if warehouse_id is None:
        return None
    warehouse = StkWarehouse.objects.filter(tenant=tenant, id=warehouse_id).first()
    if warehouse is None:
        return None

    internal_location = StkLocation.objects.filter(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_INTERNE
    ).first()
    if internal_location is None:
        return None

    stock_uom_code = get_variant_base_uom_code(variant_id)
    if stock_uom_code is not None and uom and uom != stock_uom_code:
        factor = get_conversion_factor(from_uom_code=uom, to_uom_code=stock_uom_code)
        if factor is None:
            return None
        qty = qty * factor
        uom = stock_uom_code

    needs_certificate = requires_certificate_of_analysis(variant_id)
    if needs_certificate and not lot_name:
        raise ValidationError(
            _(
                "Cet article exige un certificat d'analyse — un numéro de lot "
                "est obligatoire pour le réceptionner."
            )
        )

    supplier_location, _created = StkLocation.objects.get_or_create(
        tenant=tenant,
        warehouse=warehouse,
        type=StkLocation.TYPE_FOURNISSEUR,
        defaults={"code": f"{warehouse.code}-FRS", "name": "Fournisseur (virtuel)"},
    )

    lot = None
    if lot_name:
        lot_id = get_or_create_lot(
            tenant=tenant,
            variant_id=variant_id,
            name=lot_name,
            date_production=date_production,
            date_expiry=date_expiry,
            certificate_document_id=certificate_document_id,
        )
        lot = StkLot.objects.get(id=lot_id)
        if needs_certificate and lot.certificate_document_id is None:
            raise ValidationError(
                _("Un certificat d'analyse valide est obligatoire pour réceptionner ce lot.")
            )

    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom=uom,
        location_from=supplier_location,
        location_to=internal_location,
        date=date,
        move_type=StkMove.TYPE_RECEPTION,
        source_document=source_document,
        unit_cost_mga=unit_cost_mga,
        lot=lot,
        operator=operator,
    )
    validate_move(move)
    move_id: UUID = move.id
    return move_id


def send_to_subcontractor(
    *,
    tenant: Tenant,
    variant_id: Any,
    qty: Decimal,
    uom: str,
    warehouse_id: Any,
    date: dt.date,
    source_document: str = "",
    unit_cost_mga: Decimal = Decimal(0),
    lot_name: str = "",
    operator: User | None = None,
) -> UUID:
    """Bloc C, C2 (RG-MRP-8, PRD-9) : phase 1 (envoi) d'une sous-traitance
    de façon — interne -> sous-traitant (emplacement virtuel
    `TYPE_SOUS_TRAITANT`, `get_or_create` par entrepôt, même convention
    que `TYPE_PRODUCTION`/`TYPE_FOURNISSEUR` ci-dessus). Type de
    mouvement `TYPE_TRANSFERT_INTERNE` (PAS `TYPE_SOUS_TRAITANCE`,
    réservé à la jambe RETOUR par `services.traceability.
    _UPSTREAM_MOVE_TYPES`) : la matière reste dans le périmètre de
    valorisation TRACÉ (`_is_valuation_internal` étend désormais
    `TYPE_SOUS_TRAITANT`, PRD-9 — « la matière sortie vers un façonnier
    reste dans la valeur de stock de l'entreprise »).

    Même patron en deux phases que `services.moves.
    transfer_between_warehouses`/`receive_warehouse_transfer` (deux
    mouvements DISTINCTS et durablement persistés, jamais une seule
    transaction couvrant tout l'aller-retour) plutôt que les patrons à
    une phase (`receive_production_output`/`receive_purchase_line`) —
    l'envoi et la réception chez un sous-traitant peuvent être séparés
    de plusieurs semaines.

    Refuse (`ValidationError`) si l'entrepôt n'a aucun emplacement
    interne configuré — contrairement à `receive_purchase_line`, cette
    fonction lève plutôt que de retourner `None` : elle est appelée
    depuis un flux `mrp` explicitement déclenché par l'utilisateur
    (« Envoyer en sous-traitance »), pas depuis une réception
    automatique où un gap de configuration doit rester silencieux."""
    warehouse = StkWarehouse.objects.get(tenant=tenant, id=warehouse_id)
    source_internal = StkLocation.objects.filter(
        tenant=tenant, warehouse=warehouse, type=StkLocation.TYPE_INTERNE
    ).first()
    if source_internal is None:
        raise ValidationError(_("Cet entrepôt ne possède aucun emplacement interne configuré."))
    subcontractor_location, _created = StkLocation.objects.get_or_create(
        tenant=tenant,
        warehouse=warehouse,
        type=StkLocation.TYPE_SOUS_TRAITANT,
        defaults={"code": f"{warehouse.code}-SOUSTRAIT", "name": "Sous-traitant (virtuel)"},
    )

    lot = None
    if lot_name:
        lot_id = get_or_create_lot(tenant=tenant, variant_id=variant_id, name=lot_name)
        lot = StkLot.objects.get(id=lot_id)

    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom=uom,
        location_from=source_internal,
        location_to=subcontractor_location,
        date=date,
        move_type=StkMove.TYPE_TRANSFERT_INTERNE,
        source_document=source_document,
        unit_cost_mga=unit_cost_mga,
        lot=lot,
        operator=operator,
    )
    validate_move(move)
    move_id: UUID = move.id
    return move_id


def receive_from_subcontractor(
    *,
    tenant: Tenant,
    send_move_id: UUID,
    date: dt.date,
    qty_received: Decimal,
    qty_rejected: Decimal = Decimal(0),
    rebut_location_id: Any | None = None,
    operator: User | None = None,
) -> dict[str, UUID | None]:
    """Bloc C, C2 : phase 2 (réception) de la sous-traitance démarrée par
    `send_to_subcontractor` ci-dessus — miroir de `services.moves.
    receive_warehouse_transfer`. Sous-traitant -> interne
    (`TYPE_SOUS_TRAITANCE`, déjà réservé à cet usage exact par
    `services.traceability`) pour la quantité bonne reçue, et
    sous-traitant -> rebut (`TYPE_REBUT`, emplacement FOURNI
    explicitement par l'appelant, jamais auto-créé — même patron que
    `services.quality.apply_quality_decision`) pour la quantité rejetée.

    Réception PARTIELLE possible : `qty_received + qty_rejected` peut
    être inférieure à la quantité envoyée — le solde non réceptionné
    reste chez le sous-traitant, une réception ultérieure du même
    `send_move_id` reste possible. Refuse si la quantité demandée
    dépasse ce qui est RÉELLEMENT encore disponible chez le
    sous-traitant (`get_quant`, même garde que `receive_warehouse_
    transfer` sur son emplacement de transit, pour la même raison :
    `TYPE_SOUS_TRAITANT` est un emplacement virtuel, `_is_valuation_
    internal` l'inclut désormais mais RG-STK-10/ST7 ne s'applique
    qu'aux mouvements dont la SOURCE est un emplacement réellement
    possédé, cf. `services.moves.validate_move` — sans cette
    vérification explicite ici, une réception en trop ferait
    silencieusement passer le quant sous-traitant en négatif)."""
    send_move = StkMove.objects.select_related("location_to__warehouse").get(
        tenant=tenant, id=send_move_id, state=StkMove.STATE_DONE
    )
    subcontractor_location = send_move.location_to
    if subcontractor_location.type != StkLocation.TYPE_SOUS_TRAITANT:
        raise ValidationError(_("Ce mouvement n'est pas un envoi vers un sous-traitant."))
    if qty_received < 0 or qty_rejected < 0:
        raise ValidationError(_("Les quantités reçues/rejetées ne peuvent pas être négatives."))
    total_to_move = qty_received + qty_rejected
    if total_to_move <= 0:
        raise ValidationError(_("Au moins une quantité reçue ou rejetée doit être renseignée."))

    remaining_quant = get_quant(send_move.variant_id, subcontractor_location, send_move.lot)
    available = remaining_quant.qty if remaining_quant is not None else Decimal(0)
    if total_to_move > available:
        raise ValidationError(
            _(
                "Quantité chez le sous-traitant insuffisante pour cette réception "
                "(demandée : %(requested)s, disponible : %(available)s)."
            )
            % {"requested": total_to_move, "available": available}
        )

    destination_internal = StkLocation.objects.filter(
        tenant=tenant, warehouse=subcontractor_location.warehouse, type=StkLocation.TYPE_INTERNE
    ).first()
    if destination_internal is None:
        raise ValidationError(
            _("L'entrepôt de destination ne possède aucun emplacement interne configuré.")
        )

    received_move_id: UUID | None = None
    if qty_received > 0:
        received_move = create_move(
            tenant=tenant,
            variant_id=send_move.variant_id,
            qty=qty_received,
            uom=send_move.uom,
            location_from=subcontractor_location,
            location_to=destination_internal,
            date=date,
            move_type=StkMove.TYPE_SOUS_TRAITANCE,
            source_document=send_move.source_document,
            unit_cost_mga=send_move.unit_cost_mga,
            lot=send_move.lot,
            operator=operator,
        )
        validate_move(received_move)
        received_move_id = received_move.id

    rejected_move_id: UUID | None = None
    if qty_rejected > 0:
        if rebut_location_id is None:
            raise ValidationError(
                _("Un emplacement de rebut est requis pour une quantité rejetée.")
            )
        rebut_location = StkLocation.objects.get(tenant=tenant, id=rebut_location_id)
        rejected_move = create_move(
            tenant=tenant,
            variant_id=send_move.variant_id,
            qty=qty_rejected,
            uom=send_move.uom,
            location_from=subcontractor_location,
            location_to=rebut_location,
            date=date,
            move_type=StkMove.TYPE_REBUT,
            source_document=send_move.source_document,
            unit_cost_mga=send_move.unit_cost_mga,
            lot=send_move.lot,
            operator=operator,
        )
        validate_move(rejected_move)
        rejected_move_id = rejected_move.id

    return {"received_move_id": received_move_id, "rejected_move_id": rejected_move_id}


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


# --------------------------------------------------------------------------
# Bloc D, D1 : premiere consommation cross-app de la garde qualite/lot par
# `apps.quality` (HACCP) — `quality` ne detient jamais un `StkLot`, seulement
# son identite opaque `(tenant, variant_id, lot_name)`, meme convention que
# `lot_genealogy_tree` ci-dessus. Constantes exposees plutot que des chaines
# litterales dupliquees dans `quality` (`StkQualityState` reste un modele
# interne a `stocks`, jamais importe cross-app).
# --------------------------------------------------------------------------

QUALITY_STATE_CONFORME = StkQualityState.STATE_CONFORME
QUALITY_STATE_QUARANTINE = StkQualityState.STATE_EN_QUARANTAINE


def set_quality_state(
    tenant: Tenant,
    *,
    variant_id: Any,
    lot_name: str,
    state: str,
    description: str,
    decided_by: User,
) -> UUID | None:
    """Bloc D, D1 (QUA-1/2/3) : enveloppe PUBLIQUE de `services.quality.
    set_quality_state` pour un appelant cross-app (`apps.quality`) — motif
    (`description`) et identité (`decided_by`) rendus OBLIGATOIRES ici
    (contrairement à la fonction interne, qui les garde optionnels pour
    ses appelants historiques internes à `stocks`, ex. `apply_quality_
    decision`/`declare_recall`). Résout le lot par `(tenant, variant_id,
    lot_name)` — même convention que `lot_genealogy_tree` ci-dessus —
    jamais une instance `StkLot` passée directement (couplage cross-app
    interdit, règle de couplage n°1).

    Retourne l'UUID du `StkQualityState` créé, ou `None` (jamais une
    exception) si ce lot n'existe pas — même discipline « gap de
    configuration à la charge de l'appelant » que le reste de ce
    fichier."""
    lot = StkLot.objects.filter(tenant=tenant, variant_id=variant_id, name=lot_name).first()
    if lot is None:
        return None
    quality_state = _set_quality_state(
        tenant=tenant, lot=lot, state=state, description=description, decided_by=decided_by
    )
    quality_state_id: UUID = quality_state.id
    return quality_state_id


def list_moves_for_warehouse(tenant: Tenant, *, updated_since: Any = None) -> list[dict[str, Any]]:
    """Bloc Transverse, T1 (FOR-11) : extrait les `StkMove` VALIDÉS
    (`state=done` uniquement — un mouvement `draft`/`cancelled` n'est pas
    un fait constaté) pour alimenter `apps.analytics.AnFactMouvementStock`
    — seule voie d'accès pour `analytics`, qui ne doit jamais importer
    `apps.stocks.models` (règle de couplage n°1).

    `updated_since` (datetime ou None) filtre sur `StkMove.updated_at`
    STRICTEMENT supérieur — même contrat exact que
    `sales.services.public.list_order_lines_for_warehouse`/
    `catalog.services.public.list_variants_for_warehouse`. Renvoie des
    dicts primitifs, jamais l'objet `StkMove`."""
    qs = StkMove.objects.filter(tenant=tenant, state=StkMove.STATE_DONE).select_related(
        "location_from__warehouse", "location_to__warehouse", "lot"
    )
    if updated_since is not None:
        qs = qs.filter(updated_at__gt=updated_since)
    return [
        {
            "move_id": move.id,
            "updated_at": move.updated_at,
            "date": move.date,
            "variant_id": move.variant_id,
            "move_type": move.move_type,
            "reference": move.reference,
            "lot_name": move.lot.name if move.lot is not None else "",
            "warehouse_from_code": move.location_from.warehouse.code,
            "location_from_code": move.location_from.code,
            "warehouse_to_code": move.location_to.warehouse.code,
            "location_to_code": move.location_to.code,
            "qty": move.qty,
            "uom": move.uom,
            "unit_cost_mga": move.unit_cost_mga,
            "value_mga": move.value_mga,
            "source_document": move.source_document,
        }
        for move in qs
    ]
