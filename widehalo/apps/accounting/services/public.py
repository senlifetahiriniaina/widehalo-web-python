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
  d'approbation budgetaire).

1 gap supplementaire ajoute par ST5 de `stocks` (§5.8, cf. plan) :

- `create_stock_adjustment_entry_from_source` (RG-STK-9, "l'ecriture
  comptable de regularisation est generee automatiquement" a la
  validation d'un inventaire physique)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from apps.accounting.models import (
    AccAccount,
    AccBudget,
    AccBudgetLine,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccMoveLine,
    AccPartnerRoleAccount,
    AccPayment,
    AccPaymentTerm,
    AccPeriod,
    AccTax,
)
from apps.accounting.services.budgets import _actual_amount
from apps.accounting.services.invoices import create_invoice, create_supplier_invoice
from apps.accounting.services.landed_costs import (
    add_cost_component,
    add_landed_cost_line,
    create_landed_cost_batch,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.models.user import User


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


def create_stock_adjustment_entry_from_source(
    *,
    tenant: Tenant,
    date: dt.date,
    lines: list[dict[str, Any]],
    label: str = "",
) -> UUID | None:
    """Point d'integration appele par
    `stocks.services.inventory.validate_inventory` (RG-STK-9, §5.8, ST5)
    pour materialiser l'ecriture de regularisation d'un ajustement de
    stock (comptage cyclique/inventaire) sous forme d'`AccMove`
    (`move_type=entry`, `AccMove.TYPE_ENTRY`) — a la difference des 2 gaps
    facture (client/fournisseur) ci-dessus, ce n'est PAS une facture mais
    une ecriture diverse (double entree comptable classique, pas
    "commande -> facture").

    `lines` : `[{"account_id": UUID | None, "amount": Decimal, "label":
    str}, ...]` — `stocks` ne peut jamais passer un objet `AccAccount`
    (couplage n°1), memes primitives que `income_lines`/`expense_lines`
    des 2 autres gaps. **Convention de signe assumee (documentee ici, le
    CDC ne la precise pas)** : `amount` POSITIF = ligne au DEBIT,
    NEGATIF = ligne au CREDIT — a la difference d'une `AccMoveLine` reelle
    qui porte `debit`/`credit` comme 2 champs distincts toujours positifs,
    un seul montant signe est plus simple a construire cote appelant
    (`stocks`, qui raisonne en delta de valeur signe : + une entree de
    stock, - une sortie) ; la conversion vers `debit`/`credit` a lieu
    ICI, jamais cote appelant.

    **Resolution du compte par defaut (`account_id is None`)** : le CDC ne
    definit aucun type de compte "ecart d'inventaire" dedie parmi
    `AccAccount.TYPE_CHOICES` — convention assumee ici, par SIGNE de la
    ligne plutot que par un type unique comme les 2 autres gaps (qui n'ont
    besoin que d'un seul type de compte par defaut, cote produit/charge
    UNIQUEMENT) : une ligne positive (debit) sans compte explicite retombe
    sur le premier compte de type `AccAccount.TYPE_STOCK` du tenant (la
    valorisation de stock elle-meme) ; une ligne negative (credit) sans
    compte explicite retombe sur le premier compte de type
    `AccAccount.TYPE_EXPENSE` (le compte de charge le plus proche
    disponible pour la contrepartie d'ecart, faute d'un type "ecart
    d'inventaire" dedie — meme perte de precision assumee qu'une perte
    d'inventaire imputee en charge, gain compris, simplification
    documentee plutot qu'un nouveau `AccAccount.TYPE_CHOICES` invente sans
    fondement CDC explicite).

    Journal : premier `AccJournal.TYPE_STOCK` du tenant (type dedie deja
    present dans `AccJournal.TYPE_CHOICES`). Periode : premiere periode
    OUVERTE couvrant `date`, meme resolution exacte que les 2 autres gaps.
    Retourne `None` (jamais d'exception) si le journal, la periode, ou un
    compte a defaut sont introuvables — meme discipline "gap de
    configuration a la charge de l'administrateur du tenant" que le reste
    de ce module.

    **Equilibre debit/credit** : PAS revalide ici — `post_move` (moteur
    A4 reutilise, `services/moves.py`) leve deja `ValidationError` si le
    total debit != le total credit (RG-ACC-1), jamais duplique dans ce
    gap. Un appelant qui fournit des `lines` desequilibrees se voit donc
    refuser la publication via cette meme exception, propagee telle
    quelle (pas de `try/except` de protection : une ecriture desequilibree
    est une erreur d'appel de `stocks`, pas un gap de configuration a
    avaler silencieusement)."""
    journal = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_STOCK).first()
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

    default_stock_account: AccAccount | None = None
    default_variance_account: AccAccount | None = None
    resolved_lines: list[dict[str, Any]] = []
    for line in lines:
        amount: Decimal = line["amount"]
        account: AccAccount | None = None
        account_id = line.get("account_id")
        if account_id is not None:
            account = AccAccount.objects.filter(tenant=tenant, id=account_id).first()
        if account is None:
            if amount >= 0:
                if default_stock_account is None:
                    default_stock_account = AccAccount.objects.filter(
                        tenant=tenant, type=AccAccount.TYPE_STOCK
                    ).first()
                account = default_stock_account
            else:
                if default_variance_account is None:
                    default_variance_account = AccAccount.objects.filter(
                        tenant=tenant, type=AccAccount.TYPE_EXPENSE
                    ).first()
                account = default_variance_account
        if account is None:
            return None
        resolved_lines.append(
            {"account": account, "amount": amount, "label": line.get("label", "")}
        )

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=AccMove.TYPE_ENTRY,
        narration=label,
    )
    for line in resolved_lines:
        amount = line["amount"]
        add_line(
            move,
            account=line["account"],
            label=line["label"],
            debit=amount if amount > 0 else Decimal(0),
            credit=-amount if amount < 0 else Decimal(0),
        )

    post_move(move)
    move_id: UUID = move.id
    return move_id


def get_default_sale_tax(
    tenant: Tenant, *, on_date: dt.date | None = None
) -> dict[str, Any] | None:
    """Gap ajoute pour le module `pos` (cahier §13.5) : premiere `AccTax`
    de vente (`type=AccTax.TYPE_SALE`) valide a `on_date` (aujourd'hui par
    defaut) du tenant — `pos` ne doit jamais manipuler un objet `AccTax`
    (regle de couplage n1), chaque ligne de vente instantane le taux
    retourne ici dans `PosOrderLine.tax_rate` au moment de l'ajout (jamais
    reinterprete plus tard si l'`AccTax` change, meme discipline "document
    valide immuable" que `sales`/`accounting`).

    **Simplification assumee et disclosee** : un SEUL taux de vente par
    defaut, jamais un choix par ligne/produit (a la difference du plan de
    comptes complet d'`accounting`, qui supporte plusieurs `AccTax`) — le
    POS n'a pas, en Phase 1, de selecteur de taux par article ; c'est la
    meme simplicite que la table d'amorcage `core_regulatory_parameter`
    (`tva.taux_normal`, un taux unique) plutot qu'une matrice de taux par
    produit.

    Retourne `{"id", "rate", "account_id"}` (`account_id` = compte de TVA
    collectee de cette taxe, `AccTax.account_collected_id`, potentiellement
    `None` si non parametre) — jamais l'objet `AccTax` (regle de couplage
    n1). Retourne `None`, jamais une exception, si aucune `AccTax` de vente
    valide n'existe pour ce tenant a cette date (gap de configuration a la
    charge de l'administrateur du tenant, meme discipline que le reste de
    ce module)."""
    on_date = on_date or timezone.now().date()
    tax = (
        AccTax.objects.filter(tenant=tenant, type=AccTax.TYPE_SALE)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on_date))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
        .order_by("code")
        .first()
    )
    if tax is None:
        return None
    return {"id": tax.id, "rate": tax.rate, "account_id": tax.account_collected_id}


def create_pos_session_closing_entry_from_source(
    *,
    tenant: Tenant,
    date: dt.date,
    payment_totals: list[dict[str, Any]],
    income_amount_mga: Decimal,
    tax_amount_mga: Decimal,
    cash_variance_mga: Decimal,
    label: str = "",
) -> UUID | None:
    """Point d'integration appele par `pos.services.sessions.close_session`
    pour materialiser l'ecriture comptable CONSOLIDEE de cloture de
    session (POS-7 : "la clôture génère une écriture équilibrée sur les
    comptes PCG 2005 paramétrés pour chaque moyen de paiement") sous forme
    d'un `AccMove` (`move_type=entry`, journal `AccJournal.TYPE_CASH`).

    `payment_totals` : `[{"account_id": UUID | None, "default_account_type":
    "cash" | "bank", "amount": Decimal}, ...]` — un montant PAR MOYEN DE
    PAIEMENT de la session (le moyen `cash` porte le montant COMPTE
    physiquement, pas le montant theorique attendu — cf. `cash_variance_mga`
    ci-dessous) ; `pos` ne peut jamais passer un objet `AccAccount`
    (regle de couplage n1), `account_id` resolu ici, `None` retombant sur
    le premier `AccAccount` du `default_account_type` indique (`cash` ->
    `AccAccount.TYPE_CASH`, `bank` -> `AccAccount.TYPE_BANK` — les comptes
    de monnaie electronique du cahier, "mobile money", partagent le type
    `bank`, aucun type dedie n'existant dans `AccAccount.TYPE_CHOICES`).
    Chaque montant est DEBITE (l'encaissement augmente l'actif).

    `income_amount_mga`/`tax_amount_mga` : total HT et TVA collectee des
    ventes de la session (deja calcules par `pos`, jamais recalcules ici)
    — CREDITES sur, respectivement, le premier `AccAccount.TYPE_INCOME` et
    `AccAccount.TYPE_TAX` du tenant.

    `cash_variance_mga` : `closing_cash_counted - closing_cash_expected`
    (POS-6, "tout écart de caisse est enregistré... écriture comptable").
    Le montant COMPTE (physique) etant deja porte par la ligne `cash` de
    `payment_totals` ci-dessus (jamais le montant theorique), l'ecart
    EXISTE STRUCTURELLEMENT comme desequilibre de l'ecriture tant qu'une
    ligne de contrepartie ne l'absorbe pas — cette fonction l'ajoute
    automatiquement : un ecart NEGATIF (manquant en caisse) ajoute une
    ligne DEBIT sur le premier `AccAccount.TYPE_EXPENSE` ("perte de
    caisse") ; un ecart POSITIF (surplus) ajoute une ligne CREDIT sur le
    premier `AccAccount.TYPE_INCOME` ("gain de caisse") — meme discipline
    de resolution "par signe, faute d'un type de compte dedie" que
    `create_stock_adjustment_entry_from_source` (aucun type "ecart de
    caisse" n'existe dans `AccAccount.TYPE_CHOICES`). Un ecart nul n'ajoute
    aucune ligne.

    Journal : premier `AccJournal.TYPE_CASH` du tenant. Periode : premiere
    periode OUVERTE couvrant `date`. Retourne `None` (jamais une
    exception) si le journal, la periode, ou un compte par defaut requis
    sont introuvables — meme discipline "gap de configuration a la charge
    du tenant" que le reste de ce module ; un desequilibre debit/credit
    residuel (ne devrait jamais survenir si `income_amount_mga`/
    `tax_amount_mga`/`cash_variance_mga` sont coherents avec
    `payment_totals`) reste propage tel quel par `post_move` (RG-ACC-1),
    jamais avale.

    **Ecart assume au patron "toujours draft" des gaps facture/ajustement
    de stock** (disclosed, meme raisonnement que le gap paie) : la
    cloture d'une session de caisse EST une operation terminale et
    immuable cote `pos` (POS-9) des sa validation — publier immediatement
    l'ecriture (`post_move`), jamais la laisser en `draft`, est coherent
    avec cette finalite plutot qu'une facture (qui reste soumise a
    approbation avant publication)."""
    journal = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_CASH).first()
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

    if not payment_totals and cash_variance_mga == 0:
        return None

    default_accounts_by_type: dict[str, AccAccount | None] = {}

    def _default_account(account_type: str) -> AccAccount | None:
        if account_type not in default_accounts_by_type:
            default_accounts_by_type[account_type] = AccAccount.objects.filter(
                tenant=tenant, type=account_type
            ).first()
        return default_accounts_by_type[account_type]

    resolved_lines: list[dict[str, Any]] = []

    for entry in payment_totals:
        account: AccAccount | None = None
        account_id = entry.get("account_id")
        if account_id is not None:
            account = AccAccount.objects.filter(tenant=tenant, id=account_id).first()
        if account is None:
            account_type = (
                AccAccount.TYPE_CASH
                if entry.get("default_account_type") == "cash"
                else AccAccount.TYPE_BANK
            )
            account = _default_account(account_type)
        if account is None:
            return None
        resolved_lines.append({"account": account, "amount": entry["amount"], "label": label})

    if income_amount_mga:
        income_account = _default_account(AccAccount.TYPE_INCOME)
        if income_account is None:
            return None
        resolved_lines.append(
            {"account": income_account, "amount": -income_amount_mga, "label": label}
        )

    if tax_amount_mga:
        tax_account = _default_account(AccAccount.TYPE_TAX)
        if tax_account is None:
            return None
        resolved_lines.append({"account": tax_account, "amount": -tax_amount_mga, "label": label})

    if cash_variance_mga:
        variance_account = _default_account(
            AccAccount.TYPE_EXPENSE if cash_variance_mga < 0 else AccAccount.TYPE_INCOME
        )
        if variance_account is None:
            return None
        resolved_lines.append(
            {"account": variance_account, "amount": -cash_variance_mga, "label": label}
        )

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=AccMove.TYPE_ENTRY,
        narration=label,
    )
    for line in resolved_lines:
        amount = line["amount"]
        add_line(
            move,
            account=line["account"],
            label=line["label"],
            debit=amount if amount > 0 else Decimal(0),
            credit=-amount if amount < 0 else Decimal(0),
        )

    post_move(move)
    move_id: UUID = move.id
    return move_id


def decide_cash_journal_qualification(
    approval_request_id: UUID, decided_by: User, *, approved: bool, comment: str = ""
) -> None:
    """Enveloppe publique de `apps.accounting.services.cash_journal_import.
    decide_qualification` — seule surface autorisee pour l'ecran generique
    "Mes validations en attente" (`apps.core.api_workflow.decide_approval`,
    chantier RG-QUALIF) qui doit repercuter la decision sur le statut de
    l'`AccImportRow`, en plus de la decision `ApprovalRequest` elle-meme
    (deja geree generiquement par `apps.core.services.approvals.decide`)."""
    from apps.accounting.services.cash_journal_import import decide_qualification
    from apps.core.models.workflow import ApprovalRequest as _ApprovalRequest

    approval_request = _ApprovalRequest.objects.get(id=approval_request_id)
    decide_qualification(approval_request, decided_by, approved=approved, comment=comment)


def post_payroll_batch_entry_from_source(
    *,
    tenant: Tenant,
    date: dt.date,
    lines: list[dict[str, Any]],
    label: str = "",
) -> UUID | None:
    """Gap ajoute par le chantier `payroll` (RG-PAY-8, §5.10.6) —
    materialise l'ecriture comptable d'un LOT de paie valide, sous forme
    d'`AccMove` (`move_type=entry`, journal `AccJournal.TYPE_PAYROLL` deja
    present dans `AccJournal.TYPE_CHOICES` depuis le Lot 2 A1, jamais
    utilise avant ce chantier).

    `lines` : `[{"account_id": UUID | None, "amount": Decimal, "label":
    str, "analytic_distribution": dict | None}, ...]` — memes primitives et
    MEME convention de signe que `create_stock_adjustment_entry_from_source`
    (positif = DEBIT, negatif = CREDIT) : `payroll` raisonne en montants
    signes par ligne de regle (charges au debit, cotisations/net a payer/
    retenues au credit), la conversion vers `debit`/`credit` a lieu ICI.
    `analytic_distribution` porte la ventilation departement/atelier
    (RG-PAY-8 : "distribution analytique par departement et atelier") —
    transmise telle quelle a `add_line`, jamais reconstruite ici.

    **Resolution du compte par defaut (`account_id is None`)** : meme
    logique par SIGNE que le gap stock — ligne positive (debit, charge de
    personnel) retombe sur le premier `AccAccount.TYPE_EXPENSE` du tenant,
    ligne negative (credit, dette envers le personnel/organismes sociaux)
    retombe sur le premier `AccAccount.TYPE_PAYABLE`. `PaySalaryRule.
    account_debit_id`/`account_credit_id`, quand renseignes cote appelant,
    prevalent toujours sur ce defaut (transmis directement dans
    `account_id`).

    **Ecart assume au patron "toujours draft" des autres gaps de ce
    fichier** (disclosed, explicitement autorise par le CDC pour ce gap
    precis) : la paie EST DIFFERENTE de la facture — RG-PAY-8 dit
    litteralement que "la validation d'un lot de paie DOIT effectivement
    comptabiliser", pas seulement preparer un brouillon. Ce gap publie donc
    l'ecriture immediatement (`post_move`), jamais un simple
    `create_draft_move` laisse en `draft` comme les 3 autres gaps facture/
    ajustement de stock ci-dessus. Retourne toujours `None` (jamais
    d'exception) si le journal/la periode/un compte par defaut manquent —
    meme discipline "gap de configuration a la charge du tenant" que le
    reste de ce module ; en revanche un desequilibre debit/credit reste
    propage tel quel par `post_move` (RG-ACC-1), jamais avale."""
    journal = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_PAYROLL).first()
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

    default_expense_account: AccAccount | None = None
    default_payable_account: AccAccount | None = None
    resolved_lines: list[dict[str, Any]] = []
    for line in lines:
        amount: Decimal = line["amount"]
        account: AccAccount | None = None
        account_id = line.get("account_id")
        if account_id is not None:
            account = AccAccount.objects.filter(tenant=tenant, id=account_id).first()
        if account is None:
            if amount >= 0:
                if default_expense_account is None:
                    default_expense_account = AccAccount.objects.filter(
                        tenant=tenant, type=AccAccount.TYPE_EXPENSE
                    ).first()
                account = default_expense_account
            else:
                if default_payable_account is None:
                    default_payable_account = AccAccount.objects.filter(
                        tenant=tenant, type=AccAccount.TYPE_PAYABLE
                    ).first()
                account = default_payable_account
        if account is None:
            return None
        resolved_lines.append(
            {
                "account": account,
                "amount": amount,
                "label": line.get("label", ""),
                "analytic_distribution": line.get("analytic_distribution"),
            }
        )

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        move_type=AccMove.TYPE_ENTRY,
        narration=label,
    )
    for line in resolved_lines:
        amount = line["amount"]
        add_line(
            move,
            account=line["account"],
            label=line["label"],
            debit=amount if amount > 0 else Decimal(0),
            credit=-amount if amount < 0 else Decimal(0),
            analytic_distribution=line["analytic_distribution"],
        )

    post_move(move)
    move_id: UUID = move.id
    return move_id


def get_treasury_forecast_summary(
    tenant: Tenant, *, as_of_date: dt.date | None = None, horizon_days: int = 90
) -> dict[str, Any]:
    """Nouveau gap ajoute pendant le chantier `strategy` (rapport business
    plan, section prevision, ACC-TRESO/A15) : simple passe-plat vers
    `services/reports.py::treasury_forecast`, deja construit — aucun
    nouveau calcul ici. `tenant` expose pour la signature (coherent avec le
    reste de ce fichier) mais NON utilise pour filtrer directement, meme
    remarque que `treasury_forecast` lui-meme : l'appelant doit deja se
    trouver dans le contexte tenant courant (`TenantManager`), typiquement
    le cas d'un rapport genere pendant une requete HTTP authentifiee."""
    from apps.accounting.services.reports import treasury_forecast

    return treasury_forecast(tenant, as_of_date=as_of_date, horizon_days=horizon_days)


def get_income_statement_summary(
    tenant: Tenant, *, as_of_date: dt.date | None = None
) -> list[dict[str, Any]] | None:
    """Nouveau gap ajoute pour le module `simulation` (cahier §13.6) : passe-
    plat vers `services/reports.py::income_statement`, en resolvant
    l'exercice fiscal qui CONTIENT `as_of_date` (aujourd'hui par defaut) —
    le module `simulation` a besoin des postes du compte de resultat
    (chiffre d'affaires, achats consommes, charges de personnel, charges
    financieres...) sans connaitre l'identifiant d'exercice a l'avance,
    contrairement a `get_financial_ratios_summary` ci-dessus qui prend deja
    `fiscal_year_id` en entree. Renvoie `None` (jamais une exception) si
    aucun exercice ne couvre `as_of_date` — meme discipline "signale a
    l'ecran, ne bloque jamais silencieusement" que le reste de ce fichier
    (cf. `closing_move_id` de `apps.pos.models.PosSession`)."""
    from apps.accounting.models import AccFiscalYear
    from apps.accounting.services.reports import income_statement

    as_of = as_of_date or dt.date.today()
    fiscal_year = AccFiscalYear.objects.filter(
        tenant=tenant, date_start__lte=as_of, date_end__gte=as_of
    ).first()
    if fiscal_year is None:
        return None
    return income_statement(fiscal_year)


def get_open_settlement_items(
    tenant: Tenant, *, as_of_date: dt.date | None = None, horizon_days: int = 91
) -> list[dict[str, Any]]:
    """Passe-plat vers `services/reports.py::list_open_settlement_items` —
    nouveau gap pour le module `simulation` (SIM-7). `tenant` expose pour
    la signature (coherence avec le reste de ce fichier) mais non utilise
    pour filtrer directement, meme remarque que `get_treasury_forecast_
    summary` juste au-dessus."""
    from apps.accounting.services.reports import list_open_settlement_items

    del tenant
    return list_open_settlement_items(as_of_date=as_of_date, horizon_days=horizon_days)


def decide_invoice_import_qualification(
    approval_request_id: UUID, decided_by: User, *, approved: bool, comment: str = ""
) -> None:
    """Pendant de `decide_cash_journal_qualification` pour l'import de
    factures (`apps.accounting.services.invoice_import.
    decide_qualification`)."""
    from apps.accounting.services.invoice_import import decide_qualification
    from apps.core.models.workflow import ApprovalRequest as _ApprovalRequest

    approval_request = _ApprovalRequest.objects.get(id=approval_request_id)
    decide_qualification(approval_request, decided_by, approved=approved, comment=comment)


def get_financial_ratios_summary(tenant: Tenant, *, fiscal_year_id: UUID) -> dict[str, Any] | None:
    """Nouveau gap ajoute pendant le chantier `financing` (FIN4, rapport
    FIN-DOSSIER — section "etats financiers historiques" du dossier
    bancaire) : simple passe-plat vers `services/reports.py::
    financial_ratios` (A13), deja construit, aucun nouveau calcul ici.

    **Simplification assumee et disclosed** : plutot que d'embarquer le
    PDF complet de la liasse fiscale (`generate_liasse_is`/
    `generate_liasse_ir`, A12) dans le composite FIN-DOSSIER — ce qui
    demanderait un outillage de FUSION de flux PDF binaires jamais utilise
    ailleurs dans ce depot, tous les rapports composites existants
    (`generate_liasse_is/ir`, `STRATEGY-BP`) assemblent des SECTIONS HTML,
    jamais 2 PDF deja rendus — FIN-DOSSIER n'inclut qu'un RESUME
    (ratios financiers deja calcules par A13), coherent avec le patron
    HTML-sections-only deja etabli.

    Retourne `None` (jamais une exception) si `fiscal_year_id` ne
    correspond a aucun exercice reel de ce tenant — meme discipline que
    les autres gaps de ce fichier (`create_customer_invoice_from_source`
    et consorts, "jamais d'exception pour une configuration manquante")."""
    from apps.accounting.services.reports import financial_ratios

    fiscal_year = AccFiscalYear.objects.filter(id=fiscal_year_id, tenant=tenant).first()
    if fiscal_year is None:
        return None
    return financial_ratios(fiscal_year)


def count_unpaid_customer_invoices() -> int:
    """Nombre de factures clients validees mais non totalement soldees
    (`validated`/`paid_partially`) pour le tenant courant — deja
    tenant-scope par `AccMove.objects` (TenantManager/RLS), aucun
    parametre `tenant` necessaire ici puisque toujours appele depuis un
    cycle de requete HTTP authentifie. Utilise par le tableau de bord
    transversal (chantier UX6) — jamais un import direct de `AccMove`
    depuis `core`."""
    return AccMove.objects.filter(
        move_type=AccMove.TYPE_CUSTOMER_INVOICE,
        invoice_state__in=[AccMove.INVOICE_STATE_VALIDATED, AccMove.INVOICE_STATE_PAID_PARTIALLY],
    ).count()


def list_payment_terms(tenant: Tenant) -> list[dict[str, Any]]:
    """Gap ajoute par le chantier "creation devis/commande enrichie" de
    `sales` (DT5) : `sales` declare deja `accounting` en dependance de
    module (`apps.sales.module.MODULE.dependencies`), donc l'ajout de ce
    seul gap ne necessite aucun changement de `module.py`. Retourne des
    primitives uniquement (`id`/`name`) — jamais un `AccPaymentTerm`
    Django, meme discipline que tous les autres gaps de ce fichier (`sales`
    ne fait jamais de FK Django vers `apps.accounting`, regle de couplage
    n1). `AccPaymentTerm` reste purement informatif cote `sales`
    (`SalesQuotation.payment_term_id`/`SalesOrder.payment_term_id` : aucune
    application reelle des echeances en `sales`, hors perimetre de ce
    chantier)."""
    return [
        {"id": row["id"], "name": row["name"]}
        for row in AccPaymentTerm.objects.filter(tenant=tenant, is_active=True)
        .order_by("name")
        .values("id", "name")
    ]


def list_accounts(tenant: Tenant, *, account_type: str | None = None) -> list[dict[str, Any]]:
    """Gap ajoute par le chantier "fiche partenaire a onglets par role"
    (PT2) : liste des comptes du plan comptable du tenant, primitives
    uniquement (`id`/`code`/`name`/`type`) — jamais un `AccAccount` Django,
    meme discipline que `list_payment_terms` ci-dessus. Sert a peupler le
    selecteur de compte comptable assignable par role sur la fiche
    partenaire (`apps.partners.services.accounts`)."""
    queryset = AccAccount.objects.filter(tenant=tenant, is_active=True)
    if account_type:
        queryset = queryset.filter(type=account_type)
    return [
        {"id": row["id"], "code": row["code"], "name": row["name"], "type": row["type"]}
        for row in queryset.order_by("code").values("id", "code", "name", "type")
    ]


def assign_partner_role_account(
    tenant: Tenant, partner_id: UUID, role: str, account_id: UUID, user: User
) -> UUID | None:
    """Assigne (ou remplace) le compte comptable d'un partenaire pour un
    role donne — `update_or_create` idempotent sur `AccPartnerRoleAccount`
    (meme patron que `AccCashCategoryMapping`). Retourne `None` (jamais une
    exception) si `account_id` ne correspond a aucun compte reel de ce
    tenant — meme discipline "jamais d'exception pour une reference
    invalide" que le reste de ce fichier. Le controle RBAC
    (`accounting.manage_partneraccountassignment`) est verifie par
    l'appelant (couche vue `partners`, cf. `apps.partners.services.
    accounts`), pas ici — un check `has_perm` fonctionne independamment de
    quelle app porte la vue appelante, aucun souci de regle de couplage."""
    account = AccAccount.objects.filter(id=account_id, tenant=tenant).first()
    if account is None:
        return None
    mapping, _created = AccPartnerRoleAccount.objects.update_or_create(
        tenant=tenant,
        partner_id=partner_id,
        role=role,
        defaults={"account": account, "updated_by": user},
    )
    if _created:
        mapping.created_by = user
        mapping.save(update_fields=["created_by"])
    return mapping.id


def list_partner_role_accounts(partner_id: UUID) -> list[dict[str, Any]]:
    """Tous les comptes deja assignes a ce partenaire, un par role — deja
    tenant-scope par `AccPartnerRoleAccount.objects` (TenantManager/RLS),
    aucun parametre `tenant` necessaire (meme discipline que
    `count_unpaid_customer_invoices` ci-dessus). `id` (pk de
    `AccPartnerRoleAccount` lui-meme, pas du compte) ajoute pour PT11 :
    seul moyen pour `partners` de retrouver les entrees `AuditLog`
    rattachees a ces mappings sans jamais importer
    `apps.accounting.models`."""
    return [
        {
            "id": row.id,
            "role": row.role,
            "account_id": row.account_id,
            "account_code": row.account.code,
            "account_name": row.account.name,
        }
        for row in AccPartnerRoleAccount.objects.filter(partner_id=partner_id).select_related(
            "account"
        )
    ]


def list_ledger_entries_for_partner(partner_id: UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    """Grand livre tiers : mouvements `AccMoveLine` ou `partner_id=X`,
    tries par date decroissante — chantier "fiche partenaire a onglets par
    role" (PT4). Sert de contenu "operations comptables" pour TOUS les
    onglets de la fiche partenaire, y compris Collaborateur/Associe/Banque
    qui n'ont aucune donnee operationnelle propre a un autre module.
    Primitives uniquement, jamais un `AccMoveLine` Django."""
    from apps.accounting.models import AccMoveLine

    return [
        {
            "move_id": row["move_id"],
            "move_reference": row["move__reference"],
            "date": row["move__date"],
            "account_code": row["account__code"],
            "label": row["label"],
            "debit": row["debit"],
            "credit": row["credit"],
        }
        for row in AccMoveLine.objects.filter(partner_id=partner_id)
        .select_related("move", "account")
        .order_by("-move__date")[:limit]
        .values(
            "move_id",
            "move__reference",
            "move__date",
            "account__code",
            "label",
            "debit",
            "credit",
        )
    ]


def list_customer_invoices_for_partner(
    partner_id: UUID, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Factures clients (`AccMove.move_type=customer_invoice`) de ce
    partenaire — chantier PT4."""
    return [
        {
            "id": row["id"],
            "reference": row["reference"],
            "date": row["date"],
            "invoice_state": row["invoice_state"],
            "total_debit": row["total_debit"],
        }
        for row in AccMove.objects.filter(
            partner_id=partner_id, move_type=AccMove.TYPE_CUSTOMER_INVOICE
        )
        .order_by("-date")[:limit]
        .values("id", "reference", "date", "invoice_state", "total_debit")
    ]


def list_supplier_invoices_for_partner(
    partner_id: UUID, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Factures fournisseurs (`AccMove.move_type=supplier_invoice`) de ce
    partenaire — chantier PT4."""
    return [
        {
            "id": row["id"],
            "reference": row["reference"],
            "date": row["date"],
            "invoice_state": row["invoice_state"],
            "total_debit": row["total_debit"],
        }
        for row in AccMove.objects.filter(
            partner_id=partner_id, move_type=AccMove.TYPE_SUPPLIER_INVOICE
        )
        .order_by("-date")[:limit]
        .values("id", "reference", "date", "invoice_state", "total_debit")
    ]


def convert_amount_to_mga(
    amount: Decimal, currency: str, date: dt.date, *, tenant: Tenant
) -> Decimal:
    """Gap ajouté pour T3 (L3 Textile, cf. docs/planning/
    2026-refonte-ux-sprints.md §5, "alerte sur écart de change Ariary")
    : `financing.services.credoc.credoc_fx_variance` a besoin de
    reconvertir un montant en devise étrangère au taux du JOUR pour le
    comparer au montant MGA constaté à l'ouverture d'un crédit
    documentaire — enveloppe fine de `services.currency.convert_to_mga`
    (seule l'implémentation réelle, déjà utilisée par RG-ACC-7 dans
    `services.payments.register_payment`, jamais dupliquée ici), pour que
    `financing` n'importe jamais `apps.accounting.services.currency`
    directement (règle de couplage n°1)."""
    from apps.accounting.services.currency import convert_to_mga

    return convert_to_mga(amount, currency, date, tenant=tenant)


def list_move_lines_for_warehouse(
    tenant: Tenant, *, updated_since: Any = None
) -> list[dict[str, Any]]:
    """Gap fondations Phase 2 (cahier §12) : extrait les lignes d'écriture
    PUBLIÉES (`AccMove.state=posted` uniquement — une écriture brouillon
    reste par nature modifiable, même discipline d'immuabilité que
    RG-ACC-2/RG-ACC-3) pour alimenter `apps.analytics.AnFactEcriture`.

    `updated_since` : même contrat que `sales.services.public.
    list_order_lines_for_warehouse` (jalon incrémental)."""
    qs = AccMoveLine.objects.filter(
        move__tenant=tenant, move__state=AccMove.STATE_POSTED
    ).select_related("move", "account")
    if updated_since is not None:
        qs = qs.filter(updated_at__gt=updated_since)
    return [
        {
            "line_id": line.id,
            "updated_at": line.updated_at,
            "move_id": line.move_id,
            "move_reference": line.move.reference,
            "move_type": line.move.move_type,
            "move_date": line.move.date,
            "partner_id": line.partner_id,
            "account_id": line.account_id,
            "account_code": line.account.code,
            "account_name": line.account.name,
            "account_class": line.account.account_class,
            "debit": line.debit,
            "credit": line.credit,
        }
        for line in qs.order_by("updated_at")
    ]


def list_payments_for_warehouse(
    tenant: Tenant, *, updated_since: Any = None
) -> list[dict[str, Any]]:
    """Gap fondations Phase 2 (cahier §12) : extrait les règlements
    PUBLIÉS (`AccPayment.state=posted`) pour alimenter `apps.analytics.
    AnFactEncaissement`. `updated_since` : même contrat que ci-dessus."""
    qs = AccPayment.objects.filter(tenant=tenant, state=AccPayment.STATE_POSTED)
    if updated_since is not None:
        qs = qs.filter(updated_at__gt=updated_since)
    return [
        {
            "payment_id": payment.id,
            "updated_at": payment.updated_at,
            "reference": payment.reference,
            "date": payment.date,
            "partner_id": payment.partner_id,
            "direction": payment.direction,
            "method": payment.method,
            "amount": payment.amount,
            "state": payment.state,
        }
        for payment in qs.order_by("updated_at")
    ]


def list_accounts_for_warehouse(tenant: Tenant) -> list[dict[str, Any]]:
    """Gap fondations Phase 2 (cahier §12) : réferentiel des comptes PCG,
    INCLUANT les comptes désactivés (une écriture historique doit rester
    rattachable à son compte même si celui-ci a depuis été désactivé —
    contrairement à `list_accounts` ci-dessus, pensé pour un sélecteur de
    saisie qui ne doit proposer que des comptes actifs)."""
    return [
        {
            "account_id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "account_class": row["account_class"],
        }
        for row in AccAccount.objects.filter(tenant=tenant).values(
            "id", "code", "name", "account_class"
        )
    ]
