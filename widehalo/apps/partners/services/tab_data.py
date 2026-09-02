"""Agregation des donnees d'onglet par role pour la fiche partenaire
(chantier "fiche partenaire a onglets par role", PT12) — un seul appel
serveur, tout rendu en une page (pas de fragment HTMX par onglet).
N'importe jamais de modele d'un autre module (regle de couplage n°1) :
uniquement les gaps `services.public` deja construits en PT4-PT9."""

from __future__ import annotations

from typing import Any

from apps.accounting.services.public import list_ledger_entries_for_partner
from apps.catalog.services.public import list_supplier_products
from apps.financing.services.public import (
    list_credocs_for_bank_partner,
    list_loan_applications_for_bank_partner,
)
from apps.logistics.services.public import list_shipments_for_partner
from apps.mrp.services.public import (
    get_supplier_score,
    list_subcontract_orders_for_partner,
    list_supplier_evaluations,
)
from apps.partners.models import Partner
from apps.partners.services.accounts import get_partner_account_assignments
from apps.purchase.services.public import list_orders_for_partner as list_purchase_orders
from apps.sales.services.public import list_orders_for_partner as list_sales_orders
from apps.sales.services.public import list_quotations_for_partner


def build_role_tab_data(partner: Partner) -> dict[str, dict[str, Any]]:
    """Pour chaque role reellement present sur `partner.roles`, construit
    le contenu de l'onglet correspondant : compte comptable assigne (s'il
    existe) + operations liees issues du bon module. Le grand livre tiers
    (PT4) est toujours inclus, y compris pour Collaborateur/Associe qui
    n'ont aucune donnee operationnelle propre a un autre module (PT10)."""
    role_accounts = {row["role"]: row for row in get_partner_account_assignments(partner)}
    tabs: dict[str, dict[str, Any]] = {}
    for role in partner.roles:
        data: dict[str, Any] = {
            "account": role_accounts.get(role),
            "ledger_entries": list_ledger_entries_for_partner(partner.id),
        }
        if role == Partner.ROLE_CLIENT:
            data["quotations"] = list_quotations_for_partner(partner.id)
            data["orders"] = list_sales_orders(partner.id)
        elif role == Partner.ROLE_SUPPLIER:
            data["supplier_products"] = list_supplier_products(partner.id)
            data["purchase_orders"] = list_purchase_orders(partner.id)
        elif role == Partner.ROLE_SUBCONTRACTOR:
            data["subcontract_orders"] = list_subcontract_orders_for_partner(partner.id)
            data["supplier_score"] = get_supplier_score(partner.id)
            data["evaluations"] = list_supplier_evaluations(partner.id)
        elif role == Partner.ROLE_CARRIER:
            data["shipments"] = list_shipments_for_partner(partner.id)
        elif role == Partner.ROLE_BANK:
            data["loan_applications"] = list_loan_applications_for_bank_partner(partner.id)
            data["credocs"] = list_credocs_for_bank_partner(partner.id)
        # Associe/Collaborateur (PT10) : rien de plus que le grand livre
        # tiers deja ajoute ci-dessus, aucun gap de module supplementaire.
        tabs[role] = data
    return tabs
