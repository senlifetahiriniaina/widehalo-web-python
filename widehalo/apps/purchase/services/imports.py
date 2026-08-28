"""Couts d'importation (RG-PUR-7, §5.6, PU6 du sous-sequencement `purchase`
— cf. plan) : enveloppe fine autour du calculateur autonome A17
(`accounting.services.public.create_landed_cost_batch_from_source`) qui
construit un lot de couts d'importation a partir des lignes d'UNE
`PurOrder` deja passee a l'import.

Regle de couplage n°1 respectee : seul `apps.accounting.services.public`
est importe, jamais `apps.accounting.models` (cf. `apps/purchase/
module.py`, dependance `accounting` ajoutee par PU6)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_landed_cost_batch_from_source
from apps.purchase.models import PurOrder

# Mirroir de `apps.accounting.models.AccLandedCostBatch.METHOD_BY_VALUE` —
# constante Python distincte plutot qu'un import de modele cross-app (regle
# de couplage n°1, meme discipline documentee que `PurOrder.ORIGIN_*` face
# a `apps.catalog.models.ProductSupplierInfo.origin`, cf. `models.py`) : la
# repartition par VALEUR d'achat est le choix par defaut le plus robuste
# (toujours disponible, contrairement au poids qui exige `weight_kg` sur
# CHAQUE ligne, cf. `accounting.services.landed_costs.landed_cost_report`).
_ALLOCATION_METHOD_BY_VALUE = "by_value"


def create_import_cost_batch_for_order(
    order: PurOrder, *, cost_components: list[dict[str, Any]]
) -> UUID | None:
    """Construit un lot de couts d'importation a partir des lignes de
    `order` (`description`, `qty`, `purchase_value_mga = qty *
    unit_price_mga`) et des composants de cout fournis par l'appelant
    (`cost_components` : `{"label": str, "amount_mga": Decimal,
    "account_id": UUID | None}`, memes conventions que le gap
    `accounting` sous-jacent).

    Refuse (`ValidationError` i18n, RG METIER de `purchase` — PAS un gap
    de configuration comptable) si `order.origin == PurOrder.ORIGIN_LOCAL` :
    un lot de couts d'importation n'a de sens QUE pour une commande
    passee a l'import (RG-PUR-7), jamais pour un achat local.

    Ne leve JAMAIS d'exception pour la partie comptable : si `accounting.
    services.public.create_landed_cost_batch_from_source` retourne `None`
    (gap de configuration, ex. commande sans ligne), ce `None` est
    propage tel quel — meme discipline "jamais d'exception pour une
    configuration/donnee comptable manquante" que le reste de ce
    sous-sequencement (cf. `services/invoicing.py`)."""
    if order.origin == PurOrder.ORIGIN_LOCAL:
        raise ValidationError(
            _(
                "Un lot de couts d'importation ne peut etre cree que pour "
                "une commande passee a l'import (RG-PUR-7)."
            )
        )

    lines = [
        {
            "description": line.description,
            "qty": line.qty,
            "purchase_value_mga": line.qty * line.unit_price_mga,
            "variant_id": line.variant_id,
        }
        for line in order.lines.all()
    ]

    return create_landed_cost_batch_from_source(
        tenant=order.tenant,
        label=_("Import %(reference)s") % {"reference": order.reference},
        date=order.date,
        allocation_method=_ALLOCATION_METHOD_BY_VALUE,
        lines=lines,
        cost_components=cost_components,
        currency=order.currency,
    )
