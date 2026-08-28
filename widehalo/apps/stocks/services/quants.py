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
from uuid import UUID

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
    aucune logique de reservation construite ici en ST2."""
    qs = StkQuant.objects.filter(variant_id=variant_id)
    if location is not None:
        qs = qs.filter(location=location)
    else:
        qs = qs.filter(location__type=StkLocation.TYPE_INTERNE)
    total = Decimal(0)
    for qty, qty_reserved in qs.values_list("qty", "qty_reserved"):
        total += qty - qty_reserved
    return total
