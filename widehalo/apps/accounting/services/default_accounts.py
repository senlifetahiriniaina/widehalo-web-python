"""D10-2 — comptes par defaut du tenant (cahier Phase 1 §13.3).

Le cahier exige que « les automatismes passent par les comptes par defaut du
tenant, eux-memes rattaches au plan du referentiel actif ». Avant ce sprint,
les six gaps d'integration de `services/public.py` resolvaient leur compte par
`AccAccount.objects.filter(type=...).first()`.

Ce n'etait pas seulement implicite, c'etait **non deterministe** : `.first()`
sans `order_by` renvoie le premier compte que Postgres decide de rendre. Un
tenant ayant deux comptes de produit n'avait aucun moyen de dire lequel etait
le bon, et le resultat pouvait changer d'une execution a l'autre.

La resolution se fait desormais en deux temps :

1. le registre `AccTenantDefaultAccount` (role -> compte), configure par le
   client a l'ecran ;
2. a defaut, le repli historique par `AccAccount.type`, **desormais ordonne
   par code** donc reproductible, et journalise en avertissement : un repli
   silencieux est precisement ce qui rendait le defaut invisible.

Le repli est conserve volontairement : un tenant existant n'a aucune ligne de
registre, et faire echouer ses ecritures au motif qu'il n'a pas encore
configure ses comptes par defaut transformerait une amelioration en panne.
"""

from __future__ import annotations

import logging

from apps.accounting.models import AccAccount, AccTenantDefaultAccount
from apps.core.models.tenant import Tenant

logger = logging.getLogger(__name__)

# Type de compte servant de repli quand le role n'est pas configure. Reprend
# exactement la resolution qui etait en dur dans chaque gap de `public.py`.
ROLE_FALLBACK_TYPE: dict[str, str] = {
    AccTenantDefaultAccount.ROLE_CUSTOMER: AccAccount.TYPE_RECEIVABLE,
    AccTenantDefaultAccount.ROLE_SUPPLIER: AccAccount.TYPE_PAYABLE,
    AccTenantDefaultAccount.ROLE_SALE_INCOME: AccAccount.TYPE_INCOME,
    AccTenantDefaultAccount.ROLE_PURCHASE_EXPENSE: AccAccount.TYPE_EXPENSE,
    AccTenantDefaultAccount.ROLE_VAT: AccAccount.TYPE_TAX,
    AccTenantDefaultAccount.ROLE_BANK: AccAccount.TYPE_BANK,
    AccTenantDefaultAccount.ROLE_CASH: AccAccount.TYPE_CASH,
    AccTenantDefaultAccount.ROLE_STOCK: AccAccount.TYPE_STOCK,
    AccTenantDefaultAccount.ROLE_STOCK_VARIATION: AccAccount.TYPE_EXPENSE,
    AccTenantDefaultAccount.ROLE_CASH_DIFFERENCE: AccAccount.TYPE_EXPENSE,
    AccTenantDefaultAccount.ROLE_PAYROLL_EXPENSE: AccAccount.TYPE_EXPENSE,
    AccTenantDefaultAccount.ROLE_PAYROLL_PAYABLE: AccAccount.TYPE_PAYABLE,
}


def resolve_default_account(
    tenant: Tenant, role: str, *, fallback_type: str | None = None
) -> AccAccount | None:
    """Compte par defaut du tenant pour ce role, ou `None` si rien ne repond.

    `fallback_type` surcharge le type de repli — un seul cas l'utilise,
    l'ecart de caisse du POS, dont le sens depend du signe de l'ecart alors
    qu'un tenant ne configure qu'un seul compte d'ecart. Le registre, quand il
    est renseigne, l'emporte dans les deux sens.

    Retourne `None` plutot que de lever : c'est la discipline de toute cette
    surface publique (« aucun gap ne fait echouer le module appelant »)."""
    configured = (
        AccTenantDefaultAccount.objects.filter(tenant=tenant, role=role)
        .select_related("account")
        .first()
    )
    if configured is not None:
        return configured.account

    account_type = fallback_type or ROLE_FALLBACK_TYPE.get(role)
    if account_type is None:
        return None
    account = AccAccount.objects.filter(tenant=tenant, type=account_type).order_by("code").first()
    if account is not None:
        logger.warning(
            "Compte par defaut non configure pour le role %r (tenant %s) : repli sur le "
            "premier compte de type %r par ordre de code (%s). Configurer le registre "
            "des comptes par defaut rend ce choix explicite.",
            role,
            tenant.pk,
            account_type,
            account.code,
        )
    return account
