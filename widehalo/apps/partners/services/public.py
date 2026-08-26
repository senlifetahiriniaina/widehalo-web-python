"""Contrat public de l'app `partners` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Ne jamais importer `apps.partners.models` depuis un autre module : un module
qui a besoin de referencer un partenaire stocke son UUID (`partner_id`) et
appelle ces fonctions pour toute logique metier (cf. `catalog.ProductSupplierInfo`)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.partners.models import Partner


def is_over_credit_limit(partner_id: Any, outstanding_amount_mga: Decimal) -> bool:
    """Un `credit_limit_mga` de 0 signifie « pas de plafond » (comportement
    par defaut a la creation d'un partenaire) — jamais bloquant tant qu'il
    n'a pas ete explicitement fixe."""
    partner = Partner.objects.filter(id=partner_id).first()
    if partner is None or partner.credit_limit_mga <= 0:
        return False
    return outstanding_amount_mga > partner.credit_limit_mga


def get_partner_display_name(partner_id: Any) -> str:
    partner = Partner.objects.filter(id=partner_id).first()
    return partner.name if partner is not None else ""


def partner_has_role(partner_id: Any, role: str) -> bool:
    partner = Partner.objects.filter(id=partner_id).first()
    return partner is not None and role in partner.roles
