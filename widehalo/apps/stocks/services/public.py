"""Contrat public de l'app `stocks` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Premier gap reellement expose, ajoute pour LOG5 de `logistics` (RG-LOG-7,
cf. plan) : `apply_landed_cost_to_valuation`, appele a la cloture d'un
dossier douanier pour repercuter les couts d'approche reels sur la
valorisation du stock deja receptionne — remplace le stub documente au
Lot 2 ("stocks n'existe pas encore") maintenant que le module est
construit."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.stocks.models import StkValuationLayer


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
