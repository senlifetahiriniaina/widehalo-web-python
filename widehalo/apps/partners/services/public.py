"""Contrat public de l'app `partners` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Ne jamais importer `apps.partners.models` depuis un autre module : un module
qui a besoin de referencer un partenaire stocke son UUID (`partner_id`) et
appelle ces fonctions pour toute logique metier (cf. `catalog.ProductSupplierInfo`)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q

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
ROLE_ASSOCIATE = Partner.ROLE_ASSOCIATE
ROLE_COLLABORATOR = Partner.ROLE_COLLABORATOR
ROLE_BANK = Partner.ROLE_BANK


def list_role_choices() -> list[tuple[str, str]]:
    """Expose `Partner.ROLE_CHOICES` (code, libelle) sans jamais exposer le
    modele lui-meme — permet a un autre module (ex. `accounting`, pour
    construire le `choices=` de `AccPartnerRoleAccount.role`) de reutiliser
    la meme liste sans importer `apps.partners.models` (regle de couplage
    n°1)."""
    return list(Partner.ROLE_CHOICES)


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


def search_partners(tenant: Tenant, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Gap ajoute pour le module `pos` (§13.5) : identification optionnelle
    du client sur un ticket/facture de caisse ("un ticket anonyme est
    autorisé ; une facture nominative exige un tiers identifié"). Filtre
    texte sur le nom OU l'identifiant fiscal (NIF), insensible a la casse
    — a la difference de `find_partner_by_name` (correspondance EXACTE,
    usage RG-QUALIF), une recherche a la frappe doit accepter une
    correspondance PARTIELLE. Une chaine vide renvoie une liste vide
    (jamais tous les partenaires du tenant par defaut : contrairement au
    catalogue produit, la liste des clients n'a pas vocation a s'afficher
    en entier sur un simple focus de champ)."""
    query = query.strip()
    if not query:
        return []
    partners = Partner.objects.filter(tenant=tenant, is_placeholder=False).filter(
        Q(name__icontains=query) | Q(nif__icontains=query)
    )
    return [
        {"id": str(partner.id), "name": partner.name, "nif": partner.nif}
        for partner in partners.order_by("name")[:limit]
    ]


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


def list_partners_for_warehouse(tenant: Tenant, *, updated_since: Any = None) -> list[dict[str, Any]]:
    """Gap fondations Phase 2 (cahier §12) : réferentiel des tiers pour
    alimenter `apps.analytics.AnDimTiers` — seule voie d'accès pour
    `analytics`, qui ne doit jamais importer `apps.partners.models`.
    `updated_since` filtre sur `Partner.updated_at` (jalon incrémental,
    même contrat que `sales.services.public.list_order_lines_for_
    warehouse`)."""
    qs = Partner.objects.filter(tenant=tenant)
    if updated_since is not None:
        qs = qs.filter(updated_at__gt=updated_since)
    return [
        {
            "partner_id": partner.id,
            "updated_at": partner.updated_at,
            "code": partner.reference,
            "nom": partner.name,
            "roles": list(partner.roles),
            "is_placeholder": partner.is_placeholder,
        }
        for partner in qs.order_by("updated_at")
    ]
