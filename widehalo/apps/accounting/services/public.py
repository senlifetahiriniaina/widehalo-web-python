"""Contrat public de l'app `accounting` — seule surface que les autres
apps metier (`sales`, S4) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py).

Gap identifie par le sous-sequencement S4 de `sales` (RG-SAL-2,
facturation reelle) : `sales` ne peut jamais construire une facture
elle-meme (aucune FK Django vers `apps.accounting`, regle de couplage
n°1) — `create_customer_invoice_from_source` est le seul point
d'integration, et ne prend en entree que des UUID/primitives, jamais un
objet `accounting`."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from apps.accounting.models import AccAccount, AccJournal, AccPeriod
from apps.accounting.services.invoices import create_invoice
from apps.core.models.tenant import Tenant


def create_customer_invoice_from_source(
    *,
    tenant: Tenant,
    partner_id: UUID,
    date: dt.date,
    income_lines: list[dict[str, Any]],
    currency: str = "MGA",
) -> UUID | None:
    """Point d'integration appele par
    `sales.services.invoicing.invoice_order` pour materialiser la
    facturation reelle (RG-SAL-2) d'une commande de vente sous forme
    d'`AccMove` (`move_type=customer_invoice`).

    `income_lines` : `{"account_id": UUID | None, "amount": Decimal,
    "label": str}` — `sales` ne peut jamais passer un objet `AccAccount`
    (couplage n°1), donc chaque `account_id` est resolu ici ; s'il est
    `None`, on retombe sur un compte de produit par defaut du tenant
    (premier `AccAccount` de type `income`).

    Ne leve jamais d'exception pour une configuration comptable
    manquante — meme discipline que
    `mrp.services.public.create_manufacturing_order`/
    `catalog.services.public.get_variant_template_id` : un tenant qui n'a
    pas encore parametre son plan comptable/calendrier d'exercices n'est
    pas un bug de `sales`, c'est un gap de configuration a la charge de
    l'administrateur du tenant. Retourne `None` dans ce cas, jamais
    partiellement.

    Decision assumee (documentee ici, pas de reponse explicite du CDC) :
    la facture est retournee en etat `draft`, JAMAIS auto-validee. Le
    dispositif d'approbation a seuils existant (RG-ACC,
    `ensure_default_approval_thresholds`/`ApprovalRule`) doit pouvoir
    s'appliquer avant publication — auto-valider ici court-circuiterait
    ce controle pour toute facture generee depuis `sales`. La validation
    reste a la charge du flux comptable existant (ecrans/API `accounting`
    deja construits en A4, `POST .../invoices/{id}/validate`)."""
    journal = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_SALE).first()
    if journal is None:
        return None

    period = (
        AccPeriod.objects.filter(
            tenant=tenant,
            state=AccPeriod.STATE_OPEN,
            date_start__lte=date,
            date_end__gte=date,
        )
        .order_by("date_start")
        .first()
    )
    if period is None:
        return None

    receivable_account = AccAccount.objects.filter(
        tenant=tenant, type=AccAccount.TYPE_RECEIVABLE
    ).first()
    if receivable_account is None:
        return None

    default_income_account: AccAccount | None = None
    resolved_lines: list[dict[str, Any]] = []
    for line in income_lines:
        account: AccAccount | None = None
        account_id = line.get("account_id")
        if account_id is not None:
            account = AccAccount.objects.filter(tenant=tenant, id=account_id).first()
        if account is None:
            if default_income_account is None:
                default_income_account = AccAccount.objects.filter(
                    tenant=tenant, type=AccAccount.TYPE_INCOME
                ).first()
            if default_income_account is None:
                return None
            account = default_income_account
        resolved_lines.append(
            {"account": account, "amount": line["amount"], "label": line.get("label", "")}
        )

    move = create_invoice(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        partner_id=partner_id,
        receivable_account=receivable_account,
        income_lines=resolved_lines,
        currency=currency,
    )
    move_id: UUID = move.id
    return move_id
