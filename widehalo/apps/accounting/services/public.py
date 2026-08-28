"""Contrat public de l'app `accounting` — seule surface que les autres
apps metier (`sales`, S4) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py).

Gap identifie par le sous-sequencement S4 de `sales` (RG-SAL-2,
facturation reelle) : `sales` ne peut jamais construire une facture
elle-meme (aucune FK Django vers `apps.accounting`, regle de couplage
n°1) — `create_customer_invoice_from_source` est le seul point
d'integration, et ne prend en entree que des UUID/primitives, jamais un
objet `accounting`.

3 gaps supplementaires ajoutes par PU6 de `purchase` (§5.6, cf. plan),
meme discipline "jamais d'exception pour une configuration comptable
manquante, retourner `None`" que `create_customer_invoice_from_source` :

- `create_supplier_invoice_from_source` (RG-PUR-6, controle facture
  3 voies) ;
- `create_landed_cost_batch_from_source` (RG-PUR-7, couts d'importation) ;
- `get_budget_variance_for_analytic_account` (PUR-BUD1, routage
  d'approbation budgetaire)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.accounting.models import (
    AccAccount,
    AccBudget,
    AccBudgetLine,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.budgets import _actual_amount
from apps.accounting.services.invoices import create_invoice, create_supplier_invoice
from apps.accounting.services.landed_costs import (
    add_cost_component,
    add_landed_cost_line,
    create_landed_cost_batch,
)
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


def create_supplier_invoice_from_source(
    *,
    tenant: Tenant,
    partner_id: UUID,
    date: dt.date,
    expense_lines: list[dict[str, Any]],
    currency: str = "MGA",
) -> UUID | None:
    """Point d'integration appele par
    `purchase.services.invoicing.record_supplier_invoice` (RG-PUR-6,
    controle facture 3 voies) pour materialiser une facture fournisseur
    sous forme d'`AccMove` (`move_type=supplier_invoice`) une fois le
    controle 3 voies passe (pas de blocage).

    `expense_lines` : `{"account_id": UUID | None, "amount": Decimal,
    "label": str}` — memes conventions que `income_lines` de
    `create_customer_invoice_from_source` : `purchase` ne peut jamais
    passer un objet `AccAccount` (couplage n°1), chaque `account_id` est
    resolu ici ; s'il est `None`, on retombe sur un compte de charge par
    defaut du tenant (premier `AccAccount` de type `expense`).

    Journal (`AccJournal.TYPE_PURCHASE`) et compte fournisseur
    (`AccAccount.TYPE_PAYABLE`) resolus de la meme facon que le journal de
    vente/compte client du pendant client — ne leve jamais d'exception
    pour une configuration comptable manquante, retourne `None` (meme
    discipline, cf. docstring de `create_customer_invoice_from_source`).

    Decision assumee identique a la facture client : la facture est
    retournee en etat `draft`, JAMAIS auto-validee — la validation reste a
    la charge du flux comptable existant."""
    journal = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_PURCHASE).first()
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

    payable_account = AccAccount.objects.filter(tenant=tenant, type=AccAccount.TYPE_PAYABLE).first()
    if payable_account is None:
        return None

    default_expense_account: AccAccount | None = None
    resolved_lines: list[dict[str, Any]] = []
    for line in expense_lines:
        account: AccAccount | None = None
        account_id = line.get("account_id")
        if account_id is not None:
            account = AccAccount.objects.filter(tenant=tenant, id=account_id).first()
        if account is None:
            if default_expense_account is None:
                default_expense_account = AccAccount.objects.filter(
                    tenant=tenant, type=AccAccount.TYPE_EXPENSE
                ).first()
            if default_expense_account is None:
                return None
            account = default_expense_account
        resolved_lines.append(
            {"account": account, "amount": line["amount"], "label": line.get("label", "")}
        )

    move = create_supplier_invoice(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        partner_id=partner_id,
        payable_account=payable_account,
        expense_lines=resolved_lines,
        currency=currency,
    )
    move_id: UUID = move.id
    return move_id


def create_landed_cost_batch_from_source(
    *,
    tenant: Tenant,
    label: str,
    date: dt.date,
    allocation_method: str,
    lines: list[dict[str, Any]],
    cost_components: list[dict[str, Any]],
    currency: str = "MGA",
) -> UUID | None:
    """Point d'integration appele par
    `purchase.services.imports.create_import_cost_batch_for_order`
    (RG-PUR-7, couts d'importation) — enveloppe fine, primitives
    uniquement, autour du calculateur autonome A17 (`services/
    landed_costs.py::create_landed_cost_batch`/`add_landed_cost_line`/
    `add_cost_component`) : `purchase` ne peut jamais passer un objet
    `AccAccount`/`AccLandedCostBatch` (couplage n°1).

    `lines` : `{"description": str, "qty": Decimal, "purchase_value_mga":
    Decimal, "variant_id": UUID | None, "weight_kg": Decimal | None}`.
    `cost_components` : `{"label": str, "amount_mga": Decimal,
    "account_id": UUID | None}` — `account_id` resolu ici comme les autres
    gaps (silencieusement ignore/`None` si introuvable, un composant de
    cout sans compte impute reste un usage valide d'A17, cf.
    `add_cost_component`).

    Ne leve jamais d'exception : retourne `None` si `lines` est vide (rien
    a repartir, pas un lot valide) — a la difference des deux autres gaps
    de ce module, la creation d'un `AccLandedCostBatch` ne depend d'aucun
    parametrage comptable prealable (pas de journal/periode/compte
    obligatoire, cf. docstring de `AccLandedCostBatch`), le seul "gap de
    configuration" possible ici est donc un lot sans aucune ligne."""
    if not lines:
        return None

    batch = create_landed_cost_batch(
        tenant=tenant,
        label=label,
        date=date,
        allocation_method=allocation_method,
        currency=currency,
    )
    for line in lines:
        add_landed_cost_line(
            batch,
            description=line["description"],
            qty=line["qty"],
            purchase_value_mga=line["purchase_value_mga"],
            variant_id=line.get("variant_id"),
            weight_kg=line.get("weight_kg"),
        )
    for component in cost_components:
        account: AccAccount | None = None
        account_id = component.get("account_id")
        if account_id is not None:
            account = AccAccount.objects.filter(tenant=tenant, id=account_id).first()
        add_cost_component(
            batch, label=component["label"], amount_mga=component["amount_mga"], account=account
        )

    batch_id: UUID = batch.id
    return batch_id


def get_budget_variance_for_analytic_account(
    *,
    tenant: Tenant,
    analytic_account_id: UUID,
    fiscal_year_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Point d'integration appele par
    `purchase.services.orders.ensure_purchase_approval` (PUR-BUD1, PU6,
    cf. plan) pour la dimension budgetaire du routage d'approbation
    RG-PUR-ROUT1 : agrege l'ecart reel vs budget (A14, `services/
    budgets.py`) de TOUTES les `AccBudgetLine` du tenant rattachees a cet
    axe analytique, tous comptes/periodes confondus.

    `fiscal_year_id` optionnel : si fourni, ne considere que les lignes du
    budget de CET exercice. Si `None` (cas d'usage reel de `purchase`, qui
    ne suit aucun exercice comptable), retombe sur l'exercice OUVERT du
    tenant (`AccFiscalYear.STATE_OPEN`) — "l'exercice courant", au sens le
    plus naturel pour un appelant qui n'a lui-meme aucune notion
    d'exercice fiscal (regle de couplage n°1 : `purchase` ne peut jamais
    resoudre lui-meme un `AccFiscalYear`).

    Ne considere que les lignes d'un budget APPROUVE
    (`AccBudget.STATE_APPROVED`) — un budget en brouillon n'est pas encore
    une decision engageante, le comparer serait trompeur (meme
    raisonnement que le reste d'A14, cf. docstring de module
    `services/budgets.py`).

    Ne leve jamais d'exception pour une configuration budgetaire
    manquante (meme discipline que les 2 autres gaps de ce module) :
    retourne `None` si aucune `AccBudgetLine` approuvee ne correspond
    (aucun budget parametre pour cet axe/cet exercice n'est pas un bug de
    `purchase`, c'est un gap de configuration a la charge de
    l'administrateur du tenant).

    Retourne un resume AGREGE (somme sur toutes les lignes trouvees, pas
    une liste par ligne comme `budget_variance_report`) :
    `{"budgeted_amount_mga": Decimal, "actual_amount_mga": Decimal,
    "variance_mga": Decimal, "variance_pct": Decimal | None}` —
    `variance_pct` reste `None` sur un budget total nul (garde `_ratio_or_
    none` reprise inline, meme discipline que `budgets.py`)."""
    budget_lines_qs = AccBudgetLine.objects.filter(
        tenant=tenant,
        analytic_account_id=analytic_account_id,
        budget__state=AccBudget.STATE_APPROVED,
    )
    if fiscal_year_id is not None:
        budget_lines_qs = budget_lines_qs.filter(budget__fiscal_year_id=fiscal_year_id)
    else:
        budget_lines_qs = budget_lines_qs.filter(
            budget__fiscal_year__state=AccFiscalYear.STATE_OPEN
        )

    budget_lines = list(budget_lines_qs.select_related("account", "budget", "budget__fiscal_year"))
    if not budget_lines:
        return None

    budgeted_total = Decimal(0)
    actual_total = Decimal(0)
    for line in budget_lines:
        budgeted_total += line.budgeted_amount_mga
        actual_total += _actual_amount(line)

    variance = actual_total - budgeted_total
    return {
        "budgeted_amount_mga": budgeted_total,
        "actual_amount_mga": actual_total,
        "variance_mga": variance,
        "variance_pct": (variance / budgeted_total) if budgeted_total != 0 else None,
    }
