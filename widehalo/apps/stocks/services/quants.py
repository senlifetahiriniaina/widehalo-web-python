"""Lecture des quants (§5.8, ST2 du sous-sequencement `stocks` — cf. plan) :
primitives de consultation exposees aux ecrans/API — `StkQuant` n'est
jamais modifie ici, seulement lu (l'ecriture passe exclusivement par
`services.moves.validate_move`, cf. docstring `StkQuant` dans models.py).

**"On-hand" vs vue ledger brute** : `on_hand_qty`/`available_qty` excluent
par defaut les emplacements virtuels (`StkLocation.type != TYPE_INTERNE`)
— c'est la vue qu'un utilisateur attend intuitivement ("combien ai-je
physiquement en stock"), pas la vue comptable brute a double entree
utilisee en interne pour verifier RG-STK-1 (qui, elle, somme bien TOUS les
emplacements y compris virtuels — cf. test de propriete Hypothesis). Un
appelant qui a explicitement besoin de la vue brute passe un `location`
precis (y compris virtuel) plutot que de s'appuyer sur le defaut."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import F

from apps.stocks.models import StkLocation, StkLot, StkQuant


def get_quant(
    variant_id: UUID, location: StkLocation, lot: StkLot | None = None
) -> StkQuant | None:
    return StkQuant.objects.filter(variant_id=variant_id, location=location, lot=lot).first()


def on_hand_qty(variant_id: UUID, *, location: StkLocation | None = None) -> Decimal:
    """Somme des `qty` de quant pour `variant_id`. Si `location` est
    fourni, restreint a cet emplacement precis (virtuel ou non — la
    restriction explicite de l'appelant prime sur le filtre par defaut).
    Sinon, restreint aux emplacements INTERNES uniquement (vue "stock
    physique disponible", cf. docstring de module ci-dessus)."""
    qs = StkQuant.objects.filter(variant_id=variant_id)
    if location is not None:
        qs = qs.filter(location=location)
    else:
        qs = qs.filter(location__type=StkLocation.TYPE_INTERNE)
    total = Decimal(0)
    for qty in qs.values_list("qty", flat=True):
        total += qty
    return total


def available_qty(variant_id: UUID, *, location: StkLocation | None = None) -> Decimal:
    """`qty - qty_reserved` agrege, meme perimetre de filtrage que
    `on_hand_qty`. Primitive consommee par RG-STK-8 (reservation, ST5) —
    aucune logique de reservation construite ici en ST2.

    **STK-4 (Phase 3, sprint A2)** : un quant dont le lot est bloque
    (`StkLot.is_held()`) est exclu de l'agregat — « un lot bloque
    n'apparait ni dans le disponible... et reste present dans la valeur
    de stock » (cahier, glossaire "Emplacement"/STK-4). C'est precisement
    la distinction avec `on_hand_qty` ci-dessus, delibirement INCHANGEE :
    "disponible" (reservable/prelevable) et "present en stock/valorise"
    sont deux notions differentes, seule la premiere exclut le lot
    bloque."""
    qs = StkQuant.objects.filter(variant_id=variant_id)
    if location is not None:
        qs = qs.filter(location=location)
    else:
        qs = qs.filter(location__type=StkLocation.TYPE_INTERNE)
    total = Decimal(0)
    for quant in qs.select_related("lot"):
        if quant.lot is not None and quant.lot.is_held():
            continue
        total += quant.qty - quant.qty_reserved
    return total


def select_lot_fefo(
    variant_id: UUID, *, location: StkLocation, qty_needed: Decimal
) -> list[dict[str, Any]]:
    """STK-FEFO1 (ST6, premier perime premier sorti, §5.8) : aide de
    SELECTION de lot, expose comme une simple fonction de lecture — n'est
    JAMAIS appelee par `services.moves.validate_move`, qui garde son
    signature/comportement EXACTEMENT inchange depuis ST2/ST3.

    **Design delibere : selection de lot (FEFO) != selection de couche de
    valorisation (FIFO)** — ce sont deux notions distinctes qui ont le meme
    "air de famille" mais des responsabilites differentes. Le FIFO de
    `services.moves._consume_fifo_layers` determine QUELLE COUCHE
    `StkValuationLayer` est consommee pour le COUT d'une sortie (une
    question de VALORISATION comptable, invisible a l'operateur physique).
    Le FEFO ici determine QUEL LOT PHYSIQUE (`StkLot`, avec sa
    `date_expiry`) un prepateur doit effectivement PRELEVER en priorite
    (une question de PICKING physique, visible et actionnable par un
    operateur). Rien ne garantit que ces deux ordres coincident (un lot
    proche de peremption peut tres bien avoir ete recu APRES un autre lot
    moins urgent, donc etre une couche FIFO plus RECENTE tout en devant
    etre PRELEVE en premier au sens FEFO) — les fusionner dans une seule
    logique aurait ete metierement faux.

    **Pourquoi une fonction de SELECTION separee plutot qu'un comportement
    cache dans `validate_move`** : `validate_move` (ST2, deja committe et
    couvert par le test de propriete Hypothesis RG-STK-1/RG-STK-2) ne
    choisit jamais lui-meme QUEL lot consommer — l'appelant fournit deja
    `move.lot` explicitement (ou `None` pour un produit non trace par lot).
    Injecter une auto-selection FEFO a l'interieur de ce moteur deja
    stabilise aurait ete un changement de comportement CACHE et risque, sur
    un code deja teste et en production — plus honnete et plus sur
    d'exposer FEFO comme une primitive de LECTURE que le futur ecran/API de
    picking (hors perimetre ST6, un futur ST/ecran) appelle explicitement
    AVANT de construire ses propres `StkMove`(s) avec le(s) lot(s) ainsi
    choisi(s), plutot que de faire porter cette decision a `validate_move`
    lui-meme.

    Candidats retenus : `StkQuant` a `location` pour `variant_id`, avec
    `qty > qty_reserved` (une quantite reellement disponible, meme filtre
    que RG-STK-8) ET un `lot` dont `date_expiry` est renseignee (un quant
    sans lot, ou dont le lot n'a pas de date de peremption, n'a rien a
    apporter a un tri FEFO — HORS PERIMETRE de cette fonction, pas une
    erreur). Tries par `date_expiry` ASCENDANT (le plus proche de la
    peremption en premier), allocation GLOUTONNE de `qty_needed` a travers
    les candidats dans cet ordre — si le lot le plus urgent ne couvre pas
    l'integralite du besoin, le reliquat est pris sur le(s) lot(s)
    suivant(s) dans l'ordre FEFO, potentiellement en fractionnant
    l'allocation sur plusieurs lots.

    **STK-4 (Phase 3, sprint A2)** : tout candidat dont le lot est bloque
    (`StkLot.is_held()`) est ignore — « un lot bloque n'apparait ni dans
    le disponible, ni dans la proposition FEFO » (cahier). Le lot suivant
    dans l'ordre `date_expiry` est propose a sa place, sans erreur ni
    signalement particulier (meme discipline que l'exclusion silencieuse
    d'un candidat deja epuise, `available <= 0`, ci-dessous).

    Renvoie `[{"lot_id": UUID, "qty": Decimal}, ...]`, potentiellement une
    liste PLUS COURTE que ce qui couvrirait entierement `qty_needed` si la
    disponibilite totale des candidats est insuffisante (jamais une
    exception ni une allocation fictive au-dela du disponible reel — a
    charge de l'appelant de constater que la somme des `qty` renvoyees est
    inferieure a `qty_needed` s'il a besoin de le signaler)."""
    candidates = (
        StkQuant.objects.filter(
            tenant=location.tenant,
            variant_id=variant_id,
            location=location,
            lot__isnull=False,
            lot__date_expiry__isnull=False,
        )
        .exclude(qty__lte=F("qty_reserved"))
        .select_related("lot")
        .order_by("lot__date_expiry", "id")
    )

    remaining = qty_needed
    allocations: list[dict[str, Any]] = []
    for quant in candidates:
        if remaining <= 0:
            break
        # Garanti non-nul par le filtre `lot__isnull=False` ci-dessus.
        assert quant.lot is not None
        if quant.lot.is_held():
            continue
        available = quant.qty - quant.qty_reserved
        if available <= 0:
            continue
        take = min(available, remaining)
        allocations.append({"lot_id": quant.lot_id, "qty": take})
        remaining -= take
    return allocations
