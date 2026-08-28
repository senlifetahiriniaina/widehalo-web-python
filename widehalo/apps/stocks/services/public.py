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

from django.db import models
from django.db.models import F

from apps.stocks.models import StkLocation, StkQuant, StkValuationLayer
from apps.stocks.services.quants import available_qty
from apps.stocks.services.reservations import reserve_stock

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


def get_available_stock_qty(variant_id: Any) -> Decimal:
    """Gap ajoute pour lever le stub RG-PUR-3 de
    `purchase.services.reordering.run_reordering` (chantier de
    durcissement retroactif, cf. docstring de module) : delegation PURE a
    `services.quants.available_qty` (deja `qty - qty_reserved` agrege sur
    les emplacements INTERNES uniquement — aucun recalcul duplique ici),
    meme patron que `services.reservations.available_to_sell`."""
    return available_qty(variant_id)
