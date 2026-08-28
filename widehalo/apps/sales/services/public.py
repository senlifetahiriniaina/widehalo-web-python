"""Contrat public de l'app `sales` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

S1/S2 du sous-sequencement (cf. plan) : tracabilite d'une reference de
devis ou de commande. `purchase`/`stocks`/`payroll`/`reporting`/`strategy`
pourront s'y brancher une fois les etapes ulterieures (S3-S7) livrees."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.sales.models import SalesOrder, SalesOrderLine, SalesQuotation


def get_quotation_reference(quotation_id: Any) -> str:
    quotation = SalesQuotation.objects.filter(id=quotation_id).first()
    return quotation.reference if quotation is not None else ""


def get_order_reference(order_id: Any) -> str:
    order = SalesOrder.objects.filter(id=order_id).first()
    return order.reference if order is not None else ""


def get_delivered_qty_for_order(order_id: Any) -> Decimal | None:
    """Premier gap reel de lecture ajoute par `stocks` (ST6, RG-STK-6,
    "cohérence production/stock" — jambe "quantite livree au client") :
    somme de `SalesOrderLine.qty_delivered` (champ deja reel, cf.
    `apps.sales.models.SalesOrderLine`) sur TOUTES les lignes de la
    commande `order_id`.

    Retourne `None`, jamais une exception ni `Decimal(0)` deguise, si la
    commande n'existe pas — meme discipline "jamais de faux positif" que
    `mrp.services.public.get_order_produced_qty`/`get_supplier_score` : un
    appelant qui recoit `None` doit pouvoir distinguer "commande introuvable"
    de "commande existante mais rien livre" (`Decimal(0)`, une commande
    existante sans aucune ligne livree)."""
    if not SalesOrder.objects.filter(id=order_id).exists():
        return None
    total = SalesOrderLine.objects.filter(order_id=order_id).aggregate(total=Sum("qty_delivered"))[
        "total"
    ]
    return total if total is not None else Decimal(0)
