"""Contrat public de l'app `sales` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

S1 du sous-sequencement (cf. plan) : une seule fonction exposee, la
tracabilite d'une reference de devis. `purchase`/`stocks`/`payroll`/
`reporting`/`strategy` pourront s'y brancher une fois les etapes
ulterieures (S2-S7) livrees."""

from __future__ import annotations

from typing import Any

from apps.sales.models import SalesQuotation


def get_quotation_reference(quotation_id: Any) -> str:
    quotation = SalesQuotation.objects.filter(id=quotation_id).first()
    return quotation.reference if quotation is not None else ""
