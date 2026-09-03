"""Cycle de vie d'un mouvement de stock (§5.8, ST2 du sous-sequencement
`stocks` — cf. plan) : brouillon -> valide -> (annule), RG-STK-1 (double
entree, materialisation des quants y compris emplacements virtuels,
cf. docstrings `models.py`) et RG-STK-2 (valorisation FIFO/CMP,
`StkValuationLayer`) sont appliques ici.

**Choix de methode de valorisation (ST2)** : aucune configuration
persistante par produit n'existe dans le perimetre de ce lot (cf.
docstring `StkValuationLayer` dans `models.py`) — `validate_move` accepte
un parametre `valuation_method` (defaut `"fifo"`, seule methode
implementee ici ; `"cmp"` calcule un cout moyen pondere a l'entree mais
consomme les couches de la meme facon FIFO a la sortie, faute d'un besoin
CDC distinct documente pour un ordre de consommation different).

**Distinction inbound/outbound pour la valorisation** : une couche
`StkValuationLayer` n'est creee/consommee QUE lorsque le mouvement fait
reellement entrer ou sortir de la valeur du perimetre de stock INTERNE
trace (`StkLocation.type == TYPE_INTERNE`) — un transfert interne->interne
ne cree ni ne consomme aucune couche (la valeur ne change pas de
perimetre), un mouvement virtuel->virtuel non plus (aucun des deux cotes
n'est un stock reellement possede). C'est un perimetre distinct de la
materialisation des `StkQuant` (RG-STK-1), qui elle couvre TOUS les
emplacements sans exception.

**Ajustement ST3 (RG-STK-7) : `TYPE_REBUT` compte comme "interne" pour ce
perimetre de valorisation.** RG-STK-7 exige qu'une quantite passee en
`defaut_majeur`/`rebut` "reste valorisee jusqu'a decision" — un transfert
vers un emplacement `TYPE_REBUT` ne doit donc PAS etre traite comme une
sortie reelle du perimetre trace (ce qui consommerait des couches FIFO et
ferait disparaitre la valeur des `StkValuationLayer`), contrairement a ce
qu'un simple `type == TYPE_INTERNE` donnerait (`TYPE_REBUT` est un type
distinct de `TYPE_INTERNE` dans `StkLocation.TYPE_CHOICES`, cf. ST1). La
fonction privee `_is_valuation_internal` ci-dessous porte cette exception,
UNIQUEMENT pour cette classification interne/externe de `validate_move` —
elle ne change rien a RG-STK-1 (materialisation des quants, qui reste
inconditionnelle sur tous les types de `StkLocation`) ni au CHECK DB/garde
`create_move` (RG-STK-1 stricte, non touchee). `TYPE_INVENTAIRE` (reutilise
en ST3 comme emplacement de quarantaine faute de type dedie, cf.
`services/quality.py`) n'a PAS besoin du meme traitement : une quarantaine
(`en_quarantaine`) ne declenche aucun `StkMove` dans le perimetre ST3 (cf.
`apply_quality_decision`), donc aucun cas reel n'exercerait cette branche
pour `TYPE_INVENTAIRE` — extension non faite faute de besoin demontre,
plutot qu'ajoutee par precaution.

**Ajout ST7 (RG-STK-10, stock negatif)** : `validate_move` refuse
desormais (`ValidationError`) tout mouvement dont la source est un
emplacement "interne au sens valorisation" (`_is_valuation_internal` —
donc jamais un emplacement virtuel, qui va legitimement negatif par
construction, cf. docstring `StkQuant`) et qui ferait passer le quant
source sous zero, SAUF exception active pour ce produit
(`services.negative_stock.has_negative_stock_exception`) — auquel cas le
mouvement est autorise mais journalise et une alerte est emise (cf.
`services/negative_stock.py`). Cette garde s'execute AVANT toute
consommation de couche FIFO (`_consume_fifo_layers` ci-dessous), qui reste
donc un pur moteur de consommation, indifferent a RG-STK-10."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.stocks.models import StkLocation, StkLot, StkMove, StkQuant, StkValuationLayer
from apps.stocks.services.negative_stock import (
    _journalize_and_alert,
    has_negative_stock_exception,
)
from apps.stocks.services.quants import get_quant

VALUATION_METHOD_FIFO = "fifo"
VALUATION_METHOD_CMP = "cmp"

# Precision de stockage de tous les champs monetaires de ce module
# (`DecimalField(max_digits=18, decimal_places=4)`, meme convention que
# partout ailleurs dans ce depot).
_MGA_QUANTUM = Decimal("0.0001")


def _ratio_or_none(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Meme garde que `accounting.services.landed_costs._ratio_or_none` :
    un denominateur nul (quant/couche vide) ne doit jamais lever
    `ZeroDivisionError` — renvoie `None` plutot qu'une erreur applicative.
    Reimplementee ici plutot qu'importee (fonction privee, fichiers
    `services/` independants, meme raisonnement que `landed_costs.py`)."""
    if denominator == 0:
        return None
    return numerator / denominator


def _is_valuation_internal(location: StkLocation) -> bool:
    """Perimetre "interne" au sens VALORISATION (RG-STK-2/RG-STK-7),
    distinct du filtre `StkLocation.type == TYPE_INTERNE` utilise ailleurs
    (ex. `services.quants.on_hand_qty`, qui lui reste volontairement
    inchange — "stock physique disponible" et "perimetre de valorisation"
    sont deux notions differentes qui n'ont pas a co-evoluer). Inclut
    `TYPE_REBUT` en plus de `TYPE_INTERNE` : cf. docstring de module
    ci-dessus (ajustement ST3, RG-STK-7)."""
    return location.type in (StkLocation.TYPE_INTERNE, StkLocation.TYPE_REBUT)


def _quantize_mga(value: Decimal) -> Decimal:
    """Arrondit un montant a la precision de stockage EXACTE des champs
    `DecimalField(18,4)` (`_MGA_QUANTUM`), immediatement au moment ou il
    est calcule par une multiplication (`qty * cout`, dont le resultat a
    potentiellement plus de 4 decimales avant arrondi). Indispensable pour
    RG-STK-2 : sans cet arrondi applique ICI, la valeur en memoire (non
    arrondie) divergerait progressivement, operation apres operation, de
    ce que PostgreSQL a reellement stocke pour ce meme champ (arrondi
    implicitement a l'ecriture) — la couche lue par une operation
    ulterieure NE SERAIT PLUS celle utilisee pour calculer le total en
    memoire, cassant l'egalite exacte exigee par le test de propriete
    Hypothesis (aucune tolerance d'arrondi acceptee)."""
    return value.quantize(_MGA_QUANTUM)


def create_move(
    *,
    tenant: Tenant,
    variant_id: Any,
    qty: Decimal,
    uom: str,
    location_from: StkLocation,
    location_to: StkLocation,
    date: dt.date,
    move_type: str,
    source_document: str = "",
    unit_cost_mga: Decimal = Decimal(0),
    lot: StkLot | None = None,
    operator: User | None = None,
) -> StkMove:
    """Cree un mouvement en `draft`. Refuse (garde de service, doublee par
    le CHECK DB `stk_move_from_ne_to` sur `location_from`/`location_to`
    pour la seconde garde) si `qty <= 0` ou `location_from == location_to`
    — RG-STK-1, discipline "ceinture et bretelles" identique a RG-ACC-1.

    **RG-STK-11 (A3, hold/release qualite)** : refuse egalement tout
    mouvement d'un `lot` actuellement bloque (`StkLot.is_held()` —
    dernier `StkQualityState` en `en_quarantaine`/`defaut_majeur`/`rebut`)
    SAUF si `location_to` est elle-meme un emplacement de
    quarantaine/rebut (`TYPE_INVENTAIRE`/`TYPE_REBUT`) — c'est exactement
    le mouvement que `services.quality.apply_quality_decision` cree pour
    isoler physiquement un lot deja classe defectueux, qui doit rester
    possible. Avant A3, AUCUNE garde n'empechait de continuer a expedier/
    consommer un lot pourtant place en quarantaine (cf. docstring de
    `services.quality`, "en_quarantaine ne declenche aucun StkMove") — ce
    gap est celui que A3 comble."""
    if qty <= 0:
        raise ValidationError(
            _("La quantité d'un mouvement de stock doit être strictement positive.")
        )
    if location_from.id == location_to.id:
        raise ValidationError(
            _("Un mouvement de stock ne peut pas avoir la même origine et la même destination.")
        )
    if (
        lot is not None
        and lot.is_held()
        and location_to.type not in (StkLocation.TYPE_INVENTAIRE, StkLocation.TYPE_REBUT)
    ):
        raise ValidationError(
            _("Ce lot est bloqué pour raison qualité et ne peut pas être déplacé/expédié.")
        )
    reference = next_reference(tenant, "STKMV", date.year)
    return StkMove.objects.create(
        tenant=tenant,
        reference=reference,
        variant_id=variant_id,
        lot=lot,
        qty=qty,
        uom=uom,
        location_from=location_from,
        location_to=location_to,
        date=date,
        state=StkMove.STATE_DRAFT,
        move_type=move_type,
        source_document=source_document,
        unit_cost_mga=unit_cost_mga,
        value_mga=_quantize_mga(qty * unit_cost_mga),
        operator=operator,
    )


def _apply_quant_delta(
    *,
    tenant: Tenant,
    variant_id: Any,
    location: StkLocation,
    lot: StkLot | None,
    qty_delta: Decimal,
    value_delta: Decimal,
) -> StkQuant:
    """Applique un delta de quantite ET un delta de VALEUR (exact, jamais
    recalcule par une multiplication qty*cout qui introduirait un arrondi —
    cf. discipline "aucune tolerance d'arrondi" de RG-STK-2) au quant
    `(variant_id, location, lot)`, le creant si necessaire (patron
    `get_or_create` sous verrou de transaction — `validate_move` s'execute
    deja dans un `transaction.atomic()`). `unit_cost_mga` est recalcule en
    cout moyen pondere APRES coup (`value / qty`), purement informatif —
    jamais utilise pour deriver `value_mga`, uniquement l'inverse.

    L'appelant (`validate_move`) determine `value_delta` selon le cas :
    valeur exacte issue de la consommation FIFO reelle pour une sortie
    depuis un emplacement interne, ou `qty_delta * cout_de_reference` dans
    les autres cas (reception, transfert, mouvement virtuel<->virtuel) ou
    aucune couche de valorisation n'est en jeu."""
    quant, _created = StkQuant.objects.select_for_update().get_or_create(
        tenant=tenant, variant_id=variant_id, location=location, lot=lot
    )
    new_qty = quant.qty + qty_delta
    new_value = quant.value_mga + value_delta
    quant.qty = new_qty
    quant.value_mga = new_value
    ratio = _ratio_or_none(new_value, new_qty)
    quant.unit_cost_mga = _quantize_mga(ratio) if ratio is not None else quant.unit_cost_mga
    quant.save(update_fields=["qty", "unit_cost_mga", "value_mga"])
    return quant


def _consume_fifo_layers(
    *, tenant: Tenant, variant_id: Any, qty_to_consume: Decimal, fallback_unit_cost_mga: Decimal
) -> Decimal:
    """Consomme les couches `StkValuationLayer` disponibles pour
    `variant_id`, dans l'ordre FIFO (`date`, puis `id` a date egale — ordre
    d'insertion, stable), en decrementant `remaining_qty`/
    `remaining_value_mga`. Renvoie la valeur totale reellement consommee.

    Si les couches disponibles ne couvrent pas `qty_to_consume` (stock
    insuffisant), le reliquat non couvert est valorise au cout unitaire
    fourni par l'appelant (`fallback_unit_cost_mga`, celui du mouvement
    sortant) plutot que de lever une erreur — cette fonction elle-meme
    reste un pur moteur de consommation FIFO, indifferent au signe du
    resultat. RG-STK-10 (interdiction du stock negatif par defaut,
    exception autorisable par produit, ST7) est appliquee EN AMONT de cet
    appel, dans `validate_move` (garde explicite avant tout effet de
    bord) — cette fonction n'est donc atteinte, pour un cas qui
    consommerait plus que le stock reellement disponible, que lorsque
    `validate_move` a deja verifie qu'une exception active couvre ce
    produit."""
    layers = list(
        StkValuationLayer.objects.select_for_update()
        .filter(tenant=tenant, variant_id=variant_id, remaining_qty__gt=0)
        .order_by("date", "id")
    )
    remaining_to_consume = qty_to_consume
    total_value_consumed = Decimal(0)
    for layer in layers:
        if remaining_to_consume <= 0:
            break
        take = min(layer.remaining_qty, remaining_to_consume)
        take_value = _quantize_mga(take * layer.unit_cost_mga)
        layer.remaining_qty -= take
        layer.remaining_value_mga -= take_value
        layer.save(update_fields=["remaining_qty", "remaining_value_mga"])
        total_value_consumed += take_value
        remaining_to_consume -= take
    if remaining_to_consume > 0:
        total_value_consumed += _quantize_mga(remaining_to_consume * fallback_unit_cost_mga)
    return total_value_consumed


@transaction.atomic
def validate_move(move: StkMove, *, valuation_method: str = VALUATION_METHOD_FIFO) -> StkMove:
    """`draft -> done` : c'est ICI que l'effet reel sur le stock a lieu
    (RG-STK-1 : mise a jour des deux quants concernes ; RG-STK-2 : creation
    ou consommation d'une couche de valorisation le cas echeant). Refuse
    si le mouvement n'est pas `draft` (immuable une fois `done`, correction
    par mouvement inverse uniquement — `reverse_move`, meme discipline que
    `AccMove`/RG-ACC-2)."""
    if move.state != StkMove.STATE_DRAFT:
        raise ValidationError(_("Seul un mouvement brouillon peut être valide."))
    if valuation_method not in (VALUATION_METHOD_FIFO, VALUATION_METHOD_CMP):
        raise ValidationError(
            _("Méthode de valorisation inconnue : %(method)s") % {"method": valuation_method}
        )

    to_internal = _is_valuation_internal(move.location_to)
    from_internal = _is_valuation_internal(move.location_from)

    # RG-STK-10 (§5.8, ST7) : "Interdit par defaut. Autorisable par
    # exception, par produit, avec journalisation et alerte." — verifie
    # UNIQUEMENT quand la source est un emplacement reellement possede
    # (`_is_valuation_internal` : `TYPE_INTERNE`/`TYPE_REBUT`, cf. docstring
    # de module ci-dessus), JAMAIS pour un emplacement virtuel
    # (`fournisseur`/`client`/`production`/etc.) — ceux-la vont
    # LEGITIMEMENT negatif par construction du patron double-entree
    # (cf. docstring `StkQuant`, ST2), ce n'est pas une anomalie a bloquer.
    # Le quant source AVANT decrement fait foi (lu ici, avant tout appel a
    # `_consume_fifo_layers`/`_apply_quant_delta` qui muterait deja l'etat —
    # la garde doit s'executer avant tout effet de bord, meme si l'ensemble
    # tourne deja dans la transaction atomique de cette fonction).
    if from_internal:
        source_quant = get_quant(move.variant_id, move.location_from, move.lot)
        current_qty = source_quant.qty if source_quant is not None else Decimal(0)
        if current_qty - move.qty < 0:
            if not has_negative_stock_exception(move.variant_id):
                raise ValidationError(
                    _(
                        "Ce mouvement ferait passer le stock de ce produit en négatif a "
                        "l'emplacement %(location)s — interdit par defaut (RG-STK-10). "
                        "Une exception par produit peut etre accordee pour l'autoriser."
                    )
                    % {"location": move.location_from}
                )
            _journalize_and_alert(move)

    # RG-STK-2 : la couche/valeur consommee ou creee determine le
    # `value_delta` EXACT applique symetriquement aux deux quants (RG-STK-1)
    # — jamais deduit apres coup d'un cout unitaire arrondi, pour ne
    # jamais introduire de derive d'arrondi entre `StkQuant.value_mga` et
    # la somme des `StkValuationLayer.remaining_value_mga` (RG-STK-2,
    # aucune tolerance d'arrondi acceptee).
    if to_internal and not from_internal:
        # Reception (ou equivalent) : entree reelle de valeur dans le
        # perimetre trace — nouvelle couche FIFO/CMP creee au cout fourni
        # par l'appelant.
        value_delta = _quantize_mga(move.qty * move.unit_cost_mga)
        StkValuationLayer.objects.create(
            tenant=move.tenant,
            move=move,
            variant_id=move.variant_id,
            qty=move.qty,
            unit_cost_mga=move.unit_cost_mga,
            value_mga=value_delta,
            remaining_qty=move.qty,
            remaining_value_mga=value_delta,
            date=move.date,
        )
    elif from_internal and not to_internal:
        # Sortie reelle de valeur du perimetre trace : consommation FIFO
        # des couches existantes, `value_delta` = valeur EXACTEMENT
        # consommee (jamais recalculee via qty*cout_moyen_arrondi).
        value_delta = _consume_fifo_layers(
            tenant=move.tenant,
            variant_id=move.variant_id,
            qty_to_consume=move.qty,
            fallback_unit_cost_mga=move.unit_cost_mga,
        )
        avg_cost = _ratio_or_none(value_delta, move.qty)
        # Informatif uniquement (affichage du mouvement) — le
        # `value_delta` deja calcule ci-dessus reste la valeur de
        # reference appliquee aux quants, jamais `move.qty * move.unit_cost_mga`
        # recalcule a partir de ce cout arrondi.
        move.unit_cost_mga = _quantize_mga(avg_cost) if avg_cost is not None else Decimal(0)
        move.value_mga = value_delta
    elif to_internal and from_internal:
        # Transfert interne->interne : aucune couche touchee (la valeur ne
        # quitte jamais le perimetre trace), mais la valeur DOIT etre
        # conservee integralement d'un emplacement a l'autre — on reprend
        # le cout unitaire ACTUEL du quant source (avant decrement, d'ou
        # la lecture explicite ici) plutot que `move.unit_cost_mga` (que
        # l'appelant n'a generalement aucune raison de renseigner pour un
        # simple transfert).
        source_quant = get_quant(move.variant_id, move.location_from, move.lot)
        source_unit_cost = (
            source_quant.unit_cost_mga if source_quant is not None else move.unit_cost_mga
        )
        value_delta = _quantize_mga(move.qty * source_unit_cost)
    else:
        # Virtuel -> virtuel (degenere, aucun des deux cotes n'est un
        # stock reellement possede) : mouvement de valeur purement
        # comptable/mirroir entre deux emplacements virtuels, au cout
        # fourni par l'appelant — jamais lu par un rapport de valorisation
        # reel (RG-STK-2 ne porte que sur le stock interne trace).
        value_delta = _quantize_mga(move.qty * move.unit_cost_mga)

    # RG-STK-1 : materialisation des deux quants, y compris quand
    # l'emplacement est virtuel (cf. docstring `StkQuant`) — meme
    # `value_delta`, applique en miroir (+cote destination, -cote origine).
    _apply_quant_delta(
        tenant=move.tenant,
        variant_id=move.variant_id,
        location=move.location_to,
        lot=move.lot,
        qty_delta=move.qty,
        value_delta=value_delta,
    )
    _apply_quant_delta(
        tenant=move.tenant,
        variant_id=move.variant_id,
        location=move.location_from,
        lot=move.lot,
        qty_delta=-move.qty,
        value_delta=-value_delta,
    )

    move.state = StkMove.STATE_DONE
    move.save(update_fields=["unit_cost_mga", "value_mga", "state"])
    return move


def cancel_move(move: StkMove, *, reason: str) -> StkMove:
    """`draft -> cancelled` uniquement — un mouvement `done` est immuable
    (correction par mouvement inverse, `reverse_move`). Motif obligatoire,
    meme garde que `purchase.services.orders.cancel_order`/
    `sales.services.orders.cancel_order`."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler un mouvement de stock."))
    if move.state != StkMove.STATE_DRAFT:
        raise ValidationError(
            _("Seul un mouvement brouillon peut être annule — un mouvement valide est immuable.")
        )
    move.state = StkMove.STATE_CANCELLED
    move.cancel_reason = reason
    move.save(update_fields=["state", "cancel_reason"])
    return move


def reverse_move(move: StkMove) -> StkMove:
    """Cree un nouveau mouvement qui inverse `location_from`/`location_to`
    de `move` (meme quantite, meme lot/cout), le valide immediatement, et
    le relie via `reverses` — `move` original n'est jamais modifie (meme
    patron que `accounting.services.moves.reverse_move`, RG-ACC-2). Seul
    un mouvement `done` peut etre extourne (corriger un `draft`/`cancelled`
    n'a pas de sens, il suffit de ne jamais le valider ou de l'annuler)."""
    if move.state != StkMove.STATE_DONE:
        raise ValidationError(_("Seul un mouvement valide peut être extourne."))
    reversal = StkMove.objects.create(
        tenant=move.tenant,
        reference=next_reference(move.tenant, "STKMV", move.date.year),
        variant_id=move.variant_id,
        lot=move.lot,
        qty=move.qty,
        uom=move.uom,
        location_from=move.location_to,
        location_to=move.location_from,
        date=move.date,
        state=StkMove.STATE_DRAFT,
        move_type=move.move_type,
        source_document=move.source_document,
        unit_cost_mga=move.unit_cost_mga,
        value_mga=move.value_mga,
        operator=move.operator,
        reverses=move,
    )
    return validate_move(reversal)
