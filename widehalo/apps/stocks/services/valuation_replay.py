"""STK-12 (L12) — rejeu de la valeur de stock a une date anterieure.

Le critere : « La valeur de stock a une date anterieure, recalculee par
rejeu des mouvements, est egale au solde du compte de stock comptable a
cette meme date, a l'ariary pres. »

**Ce que ce module ferme.** Le cablage qui rend l'egalite possible existait
et etait teste mouvement par mouvement — chaque ecriture est equilibree en
elle-meme. C'est une propriete plus faible qu'il n'y parait : une ecriture
equilibree sur un mauvais montant reste equilibree. Personne ne verifiait
le CUMUL. L'audit le disait dans ces termes : « l'egalite est une
consequence attendue de la conception, non une propriete verifiee ».

**Pourquoi repartir des mouvements et non des couches.**
`StkValuationLayer.remaining_qty`/`remaining_value_mga` sont un ETAT
COURANT, ecrase a chaque sortie : aucune couche ne conserve l'historique
date de sa consommation. Les couches ne permettent donc structurellement
pas de reconstituer un etat passe. Mais c'est aussi ce qui donne au rejeu
sa valeur de preuve : **il n'emprunte pas le chemin qu'il verifie**.
Rejouer en relisant ce que le moteur a ecrit ne prouverait rien.

**Ce que le rejeu reproduit, et pourquoi si fidelement.** L'algorithme CUMP
de `services.moves._consume_average_cost` repartit la consommation
PROPORTIONNELLEMENT sur toutes les couches actives, la derniere absorbant
le reliquat d'arrondi pour garantir une somme exacte. Un rejeu qui se
contenterait d'un cout moyen glissant divergerait de quelques centiemes au
fil des operations — et le critere n'accepte aucune tolerance. Le rejeu
reconstruit donc les memes couches EN MEMOIRE et leur applique la meme
repartition. Il duplique volontairement cette arithmetique plutot que de
l'importer : une fonction partagee ferait passer les deux cotes par le
meme code, et une erreur commune s'annulerait au lieu d'etre vue.

**Le perimetre est le coeur de l'egalite, pas un detail.**
`validate_move` ne poste AUCUNE ecriture pour un transfert
interne<->interne, pour un virtuel<->virtuel, ni pour un
`TYPE_AJUSTEMENT` (que `validate_inventory` poste lui-meme, pour eviter le
double comptage). Un rejeu qui sommerait naivement tous les mouvements ne
retomberait donc jamais sur le solde comptable. Le rejeu applique le meme
perimetre de valorisation, `TYPE_REBUT` et `TYPE_SOUS_TRAITANT` compris
(RG-STK-7, PRD-8 : la matiere chez un faconnier reste dans la valeur de
stock de l'entreprise).

**Reserve a connaitre avant d'interpreter une egalite verte.**
`services.scan.py` pose `unit_cost_mga=0` par defaut : une reception au
scan cree une couche a cout zero et ne poste aucune ecriture. L'egalite
tient — les deux cotes valent zero — mais la valeur de stock est
SOUS-EVALUEE tant que le rapprochement avec le bon de commande n'a pas eu
lieu. Cette fonction prouve la coherence entre stock et comptabilite, pas
la justesse de la valorisation elle-meme.

**Seconde reserve : le stock negatif rompt l'egalite, et c'est la
comptabilite qui a tort.** Avec une exception RG-STK-10 accordee, une
sortie peut porter sur plus de quantite que le stock n'en detient.
`_consume_average_cost` valorise alors le reliquat au cout fourni par
l'appelant et le compte de stock est credite de ce montant en plus —
il descend sous zero, alors que le rejeu, lui, ne peut pas vider plus que
ce que les couches contiennent et s'arrete a zero. L'ecart vaut exactement
le reliquat non couvert. Ce n'est pas un defaut du rejeu : un compte de
stock negatif est une anomalie comptable en soi, et le rejeu la rend
visible au lieu de la masquer. `test_valuation_replay.py` en fait la
demonstration (`test_a_negative_stock_exit_breaks_the_equality...`) plutot
que de laisser cette reserve a l'etat de prose.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkLocation, StkMove

# Meme quantum que `services.moves._MGA_QUANTUM` : la precision de stockage
# EXACTE des `DecimalField(18, 4)`. Redeclare plutot qu'importe — cf.
# docstring de module sur la duplication deliberee.
_MGA_QUANTUM = Decimal("0.0001")

# Emplacements comptant comme "internes" AU SENS VALORISATION. Copie
# deliberee de `services.moves._is_valuation_internal` : le rejeu doit
# pouvoir diverger si ce perimetre change sans que personne ne s'en
# apercoive, ce qu'un import partage rendrait impossible.
_VALUATION_INTERNAL_TYPES = frozenset(
    {
        StkLocation.TYPE_INTERNE,
        StkLocation.TYPE_REBUT,
        StkLocation.TYPE_SOUS_TRAITANT,
    }
)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_MGA_QUANTUM)


@dataclass
class _ReplayLayer:
    """Couche de valorisation reconstruite en memoire — jamais lue en base."""

    remaining_qty: Decimal
    remaining_value_mga: Decimal


@dataclass
class _ReplayPool:
    """Pool de couches d'un variant, dans l'ordre d'entree."""

    layers: list[_ReplayLayer] = field(default_factory=list)

    @property
    def total_qty(self) -> Decimal:
        return sum((layer.remaining_qty for layer in self.layers), Decimal(0))

    @property
    def total_value(self) -> Decimal:
        return sum((layer.remaining_value_mga for layer in self.layers), Decimal(0))

    def add(self, *, qty: Decimal, value: Decimal) -> None:
        self.layers.append(_ReplayLayer(remaining_qty=qty, remaining_value_mga=value))

    def consume(self, *, qty: Decimal, fallback_unit_cost: Decimal) -> Decimal:
        """Repartition proportionnelle, derniere couche absorbant le
        reliquat — transcription fidele de
        `services.moves._consume_average_cost`, y compris son traitement
        de l'arrondi, sans lequel le rejeu divergerait de quelques
        centiemes et le critere n'accepte aucune tolerance."""
        active = [layer for layer in self.layers if layer.remaining_qty > 0]
        total_qty = sum((layer.remaining_qty for layer in active), Decimal(0))
        total_value = sum((layer.remaining_value_mga for layer in active), Decimal(0))

        qty_from_layers = min(qty, total_qty)
        consumed = Decimal(0)

        if qty_from_layers > 0:
            fraction = qty_from_layers / total_qty
            avg_unit_cost = total_value / total_qty
            value_from_layers = _quantize(qty_from_layers * avg_unit_cost)
            qty_left = qty_from_layers
            value_left = value_from_layers
            for index, layer in enumerate(active):
                if index == len(active) - 1:
                    qty_taken = min(qty_left, layer.remaining_qty)
                    value_taken = min(value_left, layer.remaining_value_mga)
                else:
                    qty_taken = min(
                        (layer.remaining_qty * fraction).quantize(_MGA_QUANTUM),
                        layer.remaining_qty,
                        qty_left,
                    )
                    value_taken = min(
                        _quantize(layer.remaining_value_mga * fraction),
                        layer.remaining_value_mga,
                        value_left,
                    )
                layer.remaining_qty -= qty_taken
                layer.remaining_value_mga -= value_taken
                consumed += value_taken
                qty_left -= qty_taken
                value_left -= value_taken

        remaining = qty - qty_from_layers
        if remaining > 0:
            # Reliquat non couvert par le stock existant : valorise au cout
            # du mouvement, jamais tire du pool moyen — un reliquat sans
            # couche d'origine n'a aucun cout historique a invoquer.
            consumed += _quantize(remaining * fallback_unit_cost)
        return consumed


def _replay_pools(
    tenant: Tenant, *, at_date: dt.date, variant_id: Any = None
) -> dict[Any, _ReplayPool]:
    """Rejoue chronologiquement les mouvements valides jusqu'a `at_date`.

    Ordre `(date, id)` : le meme que celui du moteur — les identifiants
    etant des UUIDv7, ils sont monotones dans le temps de creation, ce qui
    rend l'ordre stable a date egale."""
    moves = (
        StkMove.objects.filter(tenant=tenant, state=StkMove.STATE_DONE, date__lte=at_date)
        .select_related("location_from", "location_to")
        .order_by("date", "id")
    )
    if variant_id is not None:
        moves = moves.filter(variant_id=variant_id)

    pools: dict[Any, _ReplayPool] = {}
    for move in moves:
        from_internal = move.location_from.type in _VALUATION_INTERNAL_TYPES
        to_internal = move.location_to.type in _VALUATION_INTERNAL_TYPES
        pool = pools.setdefault(move.variant_id, _ReplayPool())

        if to_internal and not from_internal:
            pool.add(qty=move.qty, value=_quantize(move.qty * move.unit_cost_mga))
        elif from_internal and not to_internal:
            pool.consume(qty=move.qty, fallback_unit_cost=move.unit_cost_mga)
        # interne<->interne et virtuel<->virtuel : la valeur ne quitte pas
        # le perimetre trace, aucune couche touchee — exactement comme
        # `validate_move`, qui ne poste aucune ecriture dans ces deux cas.
    return pools


def replay_stock_value(tenant: Tenant, *, at_date: dt.date, variant_id: Any = None) -> Decimal:
    """Valeur de stock a `at_date`, rejouee depuis les mouvements (STK-12).

    C'est la grandeur que le solde du compte de stock comptable doit egaler
    a cette meme date, a l'ariary pres."""
    pools = _replay_pools(tenant, at_date=at_date, variant_id=variant_id)
    return sum((pool.total_value for pool in pools.values()), Decimal(0))


def replay_unit_cost(tenant: Tenant, *, variant_id: Any, at_date: dt.date) -> Decimal | None:
    """CUMP d'un variant A UNE DATE PASSEE (PRD-9).

    `stocks.services.public.get_variant_unit_cost` ne sait donner que le
    CUMP COURANT, lu sur les couches actives. Le critere PRD-9 exige le
    CUMP « a la date d'effet » de chaque consommation — ce que seul un
    rejeu peut fournir, les couches ne conservant aucun historique date.

    Renvoie `None`, jamais une exception, quand aucun stock n'existait a
    cette date : il n'y a alors pas de cout moyen a produire, et un zero
    serait un chiffre faux plutot qu'une absence."""
    pools = _replay_pools(tenant, at_date=at_date, variant_id=variant_id)
    pool = pools.get(variant_id)
    if pool is None or pool.total_qty <= 0:
        return None
    return _quantize(pool.total_value / pool.total_qty)
