"""Agregation des donnees d'onglet par role pour la fiche partenaire
(chantier "fiche partenaire a onglets par role", PT12) — un seul appel
serveur, tout rendu en une page (pas de fragment HTMX par onglet).
N'importe jamais de modele d'un autre module (regle de couplage n°1) :
uniquement les gaps `services.public` deja construits en PT4-PT9."""

from __future__ import annotations

from typing import Any

from apps.accounting.services.public import (
    get_partner_account_balance,
    list_ledger_entries_for_partner,
)
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
from apps.sales.services.public import (
    get_outstanding_amount_for_partner,
    list_quotations_for_partner,
)
from apps.sales.services.public import list_orders_for_partner as list_sales_orders

RECENT_SALES_DOCUMENT_COUNT = 3


def build_commercial_summary(partner: Partner) -> dict[str, Any]:
    """CRM-2 (L4) — encours, solde comptable et trois derniers documents de
    vente, **sans navigation supplementaire**.

    Le critere insiste sur ce dernier point, et c'est ce qui manquait le
    plus : la fiche affichait bien devis et commandes, mais dans l'onglet
    du role « client », donc APRES un clic — et vingt par vingt, sans
    limite. Ni l'encours ni le solde comptable n'existaient nulle part sur
    la fiche : aucun des deux n'avait de gap public, et l'encours n'etait
    meme pas une fonction (il vivait dans le corps de
    `sales.services.orders.confirm_order`).

    Ce resume est calcule pour TOUT partenaire, pas seulement pour un
    client : un fournisseur peut porter un solde comptable, et le montrer
    n'est jamais faux. Les documents de vente, eux, restent vides s'il n'y
    en a pas.

    Le solde et l'encours sont deux chiffres DIFFERENTS et le resteront :
    l'encours est commercial (commandes engagees, pas encore facturees), le
    solde est comptable (ecritures publiees). Une commande facturee quitte
    le premier pour entrer dans le second. Les afficher cote a cote sans le
    dire inviterait a les additionner."""
    return {
        "outstanding_mga": get_outstanding_amount_for_partner(partner.tenant, partner.id),
        "account_balance_mga": get_partner_account_balance(partner.tenant, partner.id),
        "recent_quotations": list_quotations_for_partner(
            partner.id, limit=RECENT_SALES_DOCUMENT_COUNT
        ),
        "recent_orders": list_sales_orders(partner.id, limit=RECENT_SALES_DOCUMENT_COUNT),
    }


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
