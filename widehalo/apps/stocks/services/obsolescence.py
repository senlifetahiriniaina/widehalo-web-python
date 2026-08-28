"""Stock dormant/obsolescence (§5.8, ST6 du sous-sequencement `stocks` —
cf. plan) : STK-OBS1 — indicateur de rotation par (produit, emplacement),
flag "dormant" au-dela d'un seuil d'immobilisation parametrable.

**Fichier separe de `services/abc_classification.py`** (plutot qu'une
extension de ce dernier) : ce sont deux notions distinctes qui repondent a
deux questions differentes — l'ABC classe un produit par sa VALEUR DE
CONSOMMATION recente (combien il "bouge" en valeur), l'obsolescence flag un
STOCK PRECIS (une combinaison variant x emplacement, pas juste un produit)
par son AGE DEPUIS LE DERNIER MOUVEMENT, independamment de sa classe ABC —
un produit classe A (forte consommation globale) peut tres bien avoir un
lot physique particulier immobilise depuis longtemps dans un coin
d'entrepot (ex. un reliquat de fin de collection), et inversement un
produit classe C peut tourner regulierement en petites quantites sans
jamais etre dormant. Regrouper les deux dans le meme fichier aurait
mélangé deux perimetres de donnees differents (`StkAbcClassification`,
une ligne par produit, vs ce rapport, une ligne par quant) pour un gain de
cohesion nul."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkLocation, StkMove, StkQuant

# STK-OBS1 : le CDC ne fixe aucun seuil precis d'immobilisation — 180 jours
# (6 mois) retenu ici comme defaut assume, coherent avec le rationnel
# textile-saisonnier deja evoque par le CDC lui-meme pour cet enrichissement
# (une saison textile dure generalement de l'ordre de 6 mois ; un stock
# encore present sans mouvement au-dela de cette duree a de bonnes chances
# d'etre un invendu de fin de collection plutot qu'un simple creux de
# rotation normal), parametrable par appel.
DEFAULT_IMMOBILIZATION_THRESHOLD_DAYS = 180


def dormant_stock_report(
    tenant: Tenant,
    *,
    as_of: dt.date | None = None,
    immobilization_threshold_days: int = DEFAULT_IMMOBILIZATION_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """Pour chaque `StkQuant` `qty > 0` a un emplacement INTERNE
    (`StkLocation.type == TYPE_INTERNE` — un stock a un emplacement virtuel
    n'a pas de sens "dormant", cf. docstring `StkQuant`), calcule le nombre
    de jours ecoules depuis le DERNIER mouvement `done` touchant ce
    `variant_id` (`StkMove.date` le plus recent, tous emplacements confondus
    — un mouvement recent ailleurs sur le meme produit reste un signal de
    rotation reelle du produit, meme si CE quant precis n'a pas ete
    directement touche) : c'est un indicateur de rotation PRODUIT, pas
    strictement "ce quant precis n'a jamais bouge depuis sa creation".

    `days_since_last_movement` reste `None` (jamais 0 ni une valeur
    inventee) quand AUCUN mouvement `done` n'existe pour ce `variant_id` —
    un quant peut exister sans mouvement `done` correspondant dans de rares
    cas de donnees incoherentes (ex. import direct) ; `is_dormant` est alors
    force a `True` (aucune trace de rotation constatee est, par construction,
    au moins aussi preoccupant qu'un age superieur au seuil).

    `is_dormant=True` quand `days_since_last_movement >
    immobilization_threshold_days` (strictement, pas `>=` — un quant dont
    l'age EGALE exactement le seuil n'a pas encore depasse la limite
    d'immobilisation acceptee)."""
    as_of = as_of or timezone.now().date()
    quants = StkQuant.objects.filter(
        tenant=tenant, qty__gt=0, location__type=StkLocation.TYPE_INTERNE
    ).select_related("location")

    rows: list[dict[str, Any]] = []
    for quant in quants:
        last_move_date = (
            StkMove.objects.filter(
                tenant=tenant, variant_id=quant.variant_id, state=StkMove.STATE_DONE
            )
            .order_by("-date")
            .values_list("date", flat=True)
            .first()
        )
        if last_move_date is None:
            days_since_last_movement: int | None = None
            is_dormant = True
        else:
            days_since_last_movement = (as_of - last_move_date).days
            is_dormant = days_since_last_movement > immobilization_threshold_days
        rows.append(
            {
                "variant_id": quant.variant_id,
                "location_id": quant.location_id,
                "qty": quant.qty,
                "value_mga": quant.value_mga,
                "days_since_last_movement": days_since_last_movement,
                "is_dormant": is_dormant,
            }
        )
    return rows
