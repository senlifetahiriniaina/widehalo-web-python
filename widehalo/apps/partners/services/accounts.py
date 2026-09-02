"""Wrapper mince vers `apps.accounting.services.public` pour le compte
comptable assigne a un partenaire par role (chantier "fiche partenaire a
onglets par role", PT3). Ne duplique aucune logique — appelle directement
les gaps deja construits en PT2. Le controle RBAC
(`accounting.manage_partneraccountassignment`) est verifie dans la VUE
`partners` qui appelle ces fonctions, pas ici : un check `request.user.
has_perm(...)` fonctionne independamment de quelle app porte la vue
appelante, aucun souci de regle de couplage (seul un import de MODELE
serait interdit, jamais un check de permission Django)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.accounting.services.public import (
    assign_partner_role_account,
    list_accounts,
    list_partner_role_accounts,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.partners.models import Partner


def get_partner_account_assignments(partner: Partner) -> list[dict[str, Any]]:
    """Tous les comptes deja assignes a ce partenaire, un par role."""
    return list_partner_role_accounts(partner.id)


def assign_partner_account(
    tenant: Tenant, partner: Partner, role: str, account_id: UUID, user: User
) -> UUID | None:
    """Assigne (ou remplace) le compte comptable de ce partenaire pour ce
    role. Retourne `None` (jamais une exception) si `account_id` ne
    correspond a aucun compte reel de ce tenant."""
    return assign_partner_role_account(tenant, partner.id, role, account_id, user)


def list_assignable_accounts(tenant: Tenant) -> list[dict[str, Any]]:
    """Comptes du plan comptable du tenant, pour peupler le selecteur de
    compte assignable sur la fiche partenaire."""
    return list_accounts(tenant)
