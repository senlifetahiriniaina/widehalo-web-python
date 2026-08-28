"""Contrat public de l'app `partners` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Ne jamais importer `apps.partners.models` depuis un autre module : un module
qui a besoin de referencer un partenaire stocke son UUID (`partner_id`) et
appelle ces fonctions pour toute logique metier (cf. `catalog.ProductSupplierInfo`)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.core.models.tenant import Tenant
from apps.core.services.entity_resolution import (
    ResolutionConfidence,
    ResolutionResult,
    normalize_name,
)
from apps.partners.models import Partner
from apps.partners.services import defaults as _defaults

# Constantes de role republiees pour les modules appelants (jamais un
# import direct de `apps.partners.models.Partner`, regle de couplage n°1)
# — utilisees avec `ensure_default_partner`/`find_partner_by_name` par
# `accounting.services.cash_journal_import`/`invoice_import` et
# `stocks.services.stock_import` (chantier RG-QUALIF).
ROLE_CLIENT = Partner.ROLE_CLIENT
ROLE_SUPPLIER = Partner.ROLE_SUPPLIER
ROLE_CARRIER = Partner.ROLE_CARRIER
ROLE_SUBCONTRACTOR = Partner.ROLE_SUBCONTRACTOR


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


def find_partner_by_name(tenant: Tenant, name: str) -> ResolutionResult:
    """Gap identifie par le chantier RG-QUALIF : resout un nom libre importe
    (colonne `PARTENAIRE`/`CLIENT`/`FOURNISSEUR` d'un fichier source) vers
    un `Partner` reel de ce tenant.

    **Simplification v1 assumee et documentee** : correspondance EXACTE
    normalisee uniquement (`apps.core.services.entity_resolution.
    normalize_name` — accents/casse/espaces ignores). Aucun algorithme de
    similarite avance (Levenshtein, phonetique...) n'est implemente —
    `ResolutionConfidence.FUZZY` n'est donc jamais retourne par cette
    fonction en v1, seulement `EXACT` (un seul partenaire actif dont le
    nom normalise correspond) ou `UNRESOLVED` (aucun partenaire ne
    correspond exactement, y compris si plusieurs partenaires partagent
    le meme nom apres normalisation — jamais de devinette sur ambiguite,
    meme discipline que `apps.accounting.services.bank_reconciliation.
    suggest_matches`). Amelioration future possible sans changer ce
    contrat : un futur v2 pourrait peupler `FUZZY` avec un candidat
    unique issu d'une similarite approximative."""
    if not name.strip():
        return ResolutionResult(confidence=ResolutionConfidence.UNRESOLVED, entity_id=None)

    target = normalize_name(name)
    candidates = list(Partner.objects.filter(tenant=tenant, is_placeholder=False))
    matches = [candidate for candidate in candidates if normalize_name(candidate.name) == target]

    if len(matches) == 1:
        return ResolutionResult(confidence=ResolutionConfidence.EXACT, entity_id=matches[0].id)
    return ResolutionResult(confidence=ResolutionConfidence.UNRESOLVED, entity_id=None)


def ensure_default_partner(tenant: Tenant, role: str) -> UUID:
    """Enveloppe publique de `apps.partners.services.defaults.
    ensure_default_partner` — seule surface autorisee pour un autre module
    metier (`accounting`, `stocks`...) qui a besoin de rattacher une ligne
    d'import a un partenaire placeholder par role (chantier RG-QUALIF).
    Retourne l'UUID, jamais l'objet `Partner` (regle de couplage n°1)."""
    partner_id: UUID = _defaults.ensure_default_partner(tenant, role).id
    return partner_id
