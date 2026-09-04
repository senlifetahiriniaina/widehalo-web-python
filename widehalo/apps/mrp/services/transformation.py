"""A2 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) : ordre
de transformation + rendement + généalogie de lot.

`MrpOrder` couvre déjà tout le cycle de vie (draft -> ... -> closed,
`services/orders.py`) — A2 n'introduit pas un nouveau type d'ordre, mais
comble deux manques réels identifiés à l'exploration :

1. **Rendement réel vs théorique** : déjà calculable sans nouveau champ
   (`qty` = quantité cible, `qty_produced` = quantité réelle, tous deux
   déjà sur `MrpOrder`) — `order_yield` expose juste ce calcul en un seul
   appel plutôt que de le dupliquer côté vue/template.

2. **Généalogie de lot amont/aval** : `mrp` ne créait jusqu'ici AUCUN
   `StkMove`/`StkLot` (cf. docstring de
   `apps.stocks.services.consistency.production_consistency_report`, qui
   documente ce manque pour RG-STK-6) et `MrpOrderComponent.lot`
   (`CharField` libre) n'était renseigné nulle part. `finish_transformation_order`
   ferme ces deux manques ENSEMBLE à la clôture d'un ordre : réception du
   lot de sortie en stock (`stocks.services.public.receive_production_output`)
   et liaison généalogique avec chaque lot de composant déjà renseigné sur
   `order.components` (`record_component_consumption` ci-dessous, appelé
   par l'utilisateur pendant la production, AVANT la clôture)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.mrp.models import MrpOrder, MrpOrderComponent
from apps.mrp.services.orders import finish_order
from apps.stocks.services.public import (
    list_locations,
    lot_genealogy_tree,
    receive_production_output,
    record_lot_genealogy,
)


def record_component_consumption(
    component: MrpOrderComponent, *, lot_name: str, qty_consumed: Decimal
) -> MrpOrderComponent:
    """Renseigne le lot et la quantité réellement consommés pour un
    composant planifié — à faire AVANT la clôture de l'ordre
    (`finish_transformation_order`), pour que la généalogie puisse lier ce
    lot au lot de sortie. `qty_consumed` doit être positive : une
    correction à zéro se fait en ne créant simplement pas de lien
    généalogique (`record_lot_genealogy` ignore silencieusement une
    quantité nulle/négative, cf. sa docstring).

    Bloc C, C4/PRD-10 : refuse toute déclaration sur un ordre déjà clôturé
    ou annulé — y compris par appel direct de l'API, pas seulement par
    l'écran (qui ne propose déjà plus l'action à ce stade)."""
    if component.order.state in (MrpOrder.STATE_CLOSED, MrpOrder.STATE_CANCELLED):
        raise ValidationError(
            _("Impossible de déclarer une consommation sur un ordre clôturé ou annulé.")
        )
    if qty_consumed < 0:
        raise ValidationError(_("La quantité consommée ne peut pas être négative."))
    component.lot = lot_name
    component.qty_consumed = qty_consumed
    component.save(update_fields=["lot", "qty_consumed"])
    return component


def finish_transformation_order(
    order: MrpOrder,
    user: User,
    *,
    qty_produced: Decimal,
    output_lot_name: str,
    location_to_id: Any,
    qty_scrapped: Decimal = Decimal(0),
    date: dt.date | None = None,
) -> MrpOrder:
    """Clôture "transformation" d'un ordre : transition FSM standard
    (`finish_order`, inchangée) + réception du lot de sortie en stock +
    généalogie depuis chaque composant dont le lot a été renseigné
    (`record_component_consumption`). `output_lot_name` vide désactive
    tout le volet stock/généalogie (ordre textile/hors-agro qui n'a pas
    besoin de traçabilité de lot) — comportement strictement identique à
    l'ancien `finish_order` dans ce cas, aucune régression pour les ordres
    existants."""
    date = date or timezone.now().date()
    if output_lot_name and not location_to_id:
        raise ValidationError(
            _("Un emplacement de réception est requis pour enregistrer un lot de sortie.")
        )
    # Transaction unique (RG-MRP/A2) : la transition FSM ET la réception en
    # stock/généalogie doivent réussir ou échouer ENSEMBLE — avant ce
    # correctif, un échec de `receive_production_output` (ex. emplacement
    # invalide) après une transition déjà validée laissait l'ordre `done`
    # sans aucune réception de stock ni généalogie, silencieusement.
    with transaction.atomic():
        order = finish_order(order, user, qty_produced=qty_produced, qty_scrapped=qty_scrapped)

        if not output_lot_name:
            return order

        receive_production_output(
            tenant=order.tenant,
            variant_id=order.variant_id,
            qty=qty_produced,
            location_to_id=location_to_id,
            date=date,
            source_document=order.reference,
            lot_name=output_lot_name,
        )
        for component in order.components.all():
            if not component.lot or component.qty_consumed <= 0 or component.variant_id is None:
                continue
            record_lot_genealogy(
                tenant=order.tenant,
                parent_variant_id=component.variant_id,
                parent_lot_name=component.lot,
                child_variant_id=order.variant_id,
                child_lot_name=output_lot_name,
                qty=component.qty_consumed,
                source_document=order.reference,
            )

        order.output_lot_name = output_lot_name
        order.save(update_fields=["output_lot_name"])
        return order


def order_yield(order: MrpOrder) -> dict[str, Any]:
    """Rendement réel vs théorique (critère d'acceptation A2). Le
    "théorique" retenu est la quantité cible de l'ordre (`qty`) — le CDC
    ne définit aucun autre théorique calculable (pas de notion de
    rendement matière par composant dans `MrpBomLine`, cf. exploration) ;
    `yield_pct` vaut `None` (jamais une division par zéro) si `qty` est
    nulle."""
    yield_pct = (order.qty_produced / order.qty * 100) if order.qty else None
    return {
        "qty_target": order.qty,
        "qty_produced": order.qty_produced,
        "qty_scrapped": order.qty_scrapped,
        "yield_pct": yield_pct,
    }


def order_genealogy(order: MrpOrder) -> dict[str, Any] | None:
    """Arbre de généalogie du lot de sortie de l'ordre — `None` si l'ordre
    n'a pas (encore) de lot de sortie renseigné (ordre non clôturé en
    transformation, ou clôturé sans généalogie car `output_lot_name` non
    fourni)."""
    if not order.output_lot_name or order.variant_id is None:
        return None
    return lot_genealogy_tree(
        tenant=order.tenant, variant_id=order.variant_id, name=order.output_lot_name
    )


def available_output_locations(order: MrpOrder) -> list[dict[str, Any]]:
    """Emplacements disponibles pour le sélecteur `location_to_id` du
    formulaire de clôture — enveloppe fine de
    `stocks.services.public.list_locations`, pour que la vue `mrp` n'ait
    jamais à importer `apps.stocks.services.public` elle-même (une seule
    surface de dépendance côté `mrp`, ce module)."""
    return list_locations(order.tenant)
