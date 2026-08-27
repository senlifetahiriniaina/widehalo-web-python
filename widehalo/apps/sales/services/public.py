"""Contrat public de l'app `sales` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

S1/S2 du sous-sequencement (cf. plan) : tracabilite d'une reference de
devis ou de commande. `purchase`/`stocks`/`payroll`/`reporting`/`strategy`
pourront s'y brancher une fois les etapes ulterieures (S3-S7) livrees."""

from __future__ import annotations

from typing import Any

from apps.sales.models import SalesOrder, SalesQuotation


def get_quotation_reference(quotation_id: Any) -> str:
    quotation = SalesQuotation.objects.filter(id=quotation_id).first()
    return quotation.reference if quotation is not None else ""


def get_order_reference(order_id: Any) -> str:
    order = SalesOrder.objects.filter(id=order_id).first()
    return order.reference if order is not None else ""
