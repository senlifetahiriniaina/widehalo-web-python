"""Redistribution inter-sites (STK-REDIS1, §5.8, ST6 du sous-sequencement
`stocks` — cf. plan) : suggestion de transfert entre entrepots quand l'un
est en rupture (ou proche) et qu'un autre a de l'excedent, pour le meme
produit.

**Suggestion, jamais un transfert impose** — meme discipline exacte que
RG-LOG-4/LOG-TOUR1 ("suggestion modifiable, jamais imposee", cf. plan
section `logistics`) : `suggest_redistribution` ne cree AUCUN `StkMove`/
`StkPicking` lui-meme, elle renvoie une liste de suggestions que l'appelant
(ecran/API futur) peut choisir de suivre, modifier, ou ignorer.

**Pas d'algorithme d'optimisation** : le CDC classe cet enrichissement
"Adapter" (pas "Adopter") — un simple appariement "site en rupture X, site
en excedent Y" a une passe unique suffit, sans aucune notion de cout de
transport, de delai, ni de repartition optimale entre plusieurs sites
excedentaires simultanes. Quand plusieurs sites ont de l'excedent pour le
meme produit, celui avec le PLUS d'excedent est retenu (choix simple et
deterministe, documente ici plutot qu'une regle de priorite plus fine
inventee sans commanditaire CDC)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkLocation, StkQuant


def suggest_redistribution(
    tenant: Tenant, *, shortage_threshold: Decimal = Decimal(0)
) -> list[dict[str, Any]]:
    """Pour chaque `variant_id` ayant au moins un `StkQuant` en rupture
    (`qty <= shortage_threshold`) a un emplacement INTERNE d'un
    `StkWarehouse`, cherche si un AUTRE entrepot a un excedent reel pour le
    meme produit (`qty - qty_reserved > 0`, signal "a de la marge
    disponible" le plus simple et le plus defendable — pas de prevision de
    demande, cf. docstring de module) et, si oui, suggere un transfert.

    **`suggested_qty` = `min(shortage_qty, available_excess_qty)`** :
    - `shortage_qty` = `shortage_threshold - qty` du quant en rupture (le
      manque exact pour atteindre le seuil, jamais negatif car le quant est
      deja filtre `qty <= shortage_threshold`) ;
    - `available_excess_qty` = `qty - qty_reserved` du quant excedentaire
      retenu (l'entrepot avec le PLUS d'excedent parmi les candidats, cf.
      docstring de module).

    Une ligne par (variant, emplacement en rupture) — si plusieurs
    emplacements en rupture existent pour le meme produit dans le meme
    entrepot, chacun recoit sa propre suggestion (les besoins ne sont pas
    consolides au niveau produit ici, simplicite assumee). Aucune
    suggestion n'est renvoyee pour un couple sans excedent disponible
    ailleurs, ni pour un quant qui n'est pas en rupture."""
    shortages = StkQuant.objects.filter(
        tenant=tenant, location__type=StkLocation.TYPE_INTERNE, qty__lte=shortage_threshold
    ).select_related("location__warehouse")

    suggestions: list[dict[str, Any]] = []
    for shortage_quant in shortages:
        shortage_warehouse_id = shortage_quant.location.warehouse_id
        excess_candidates = (
            StkQuant.objects.filter(
                tenant=tenant,
                variant_id=shortage_quant.variant_id,
                location__type=StkLocation.TYPE_INTERNE,
            )
            .exclude(location__warehouse_id=shortage_warehouse_id)
            .select_related("location__warehouse")
        )
        best_excess_quant = None
        best_excess_qty = Decimal(0)
        for candidate in excess_candidates:
            excess = candidate.qty - candidate.qty_reserved
            if excess > best_excess_qty:
                best_excess_qty = excess
                best_excess_quant = candidate
        if best_excess_quant is None:
            continue

        shortage_qty = shortage_threshold - shortage_quant.qty
        suggested_qty = min(shortage_qty, best_excess_qty)
        suggestions.append(
            {
                "variant_id": shortage_quant.variant_id,
                "from_warehouse_id": best_excess_quant.location.warehouse_id,
                "from_location_id": best_excess_quant.location_id,
                "to_warehouse_id": shortage_warehouse_id,
                "to_location_id": shortage_quant.location_id,
                "suggested_qty": suggested_qty,
                "shortage_qty": shortage_qty,
                "available_excess_qty": best_excess_qty,
            }
        )
    return suggestions
