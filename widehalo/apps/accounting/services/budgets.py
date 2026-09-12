"""A14 (Phase 2 `accounting`) : budgets et analyse d'ecart (`acc_budget`/
`acc_budget_line`, ACC-BUDGET implicite du plan). Aucun canevas fiscal
reconstruit ici (contrairement a `chart_of_accounts.py`/`reports.py`) — pas
de reserve OECFM necessaire, cette etape ne provient pas de l'annexe PDF
mais de la checklist de report deja actee au plan.

**Simplification assumee (pas de versioning de budget)** : une fois
`state="approved"`, un budget devient IMMUABLE a l'ajout de ligne
(`add_budget_line` refuse). Une vraie revision budgetaire creerait un
NOUVEAU budget (nouvelle instance `AccBudget`, meme `fiscal_year`), jamais
une modification retroactive d'un budget deja approuve — coherent avec la
philosophie "explicabilite d'abord" deja appliquee ailleurs dans ce module
(RG-SAL-8, `register_asset`) : un historique de decision budgetaire doit
rester lisible, pas reecrit sur place. Aucun mecanisme de "version N+1
derivee de la version N" n'est construit ici : hors perimetre A14 tel que
formule au plan ("comparaison reel vs budget, rapport d'ecart" — rien sur le
versioning), a construire dans un lot ulterieur si le besoin se confirme.

**Resolution de l'ambiguite `AccBudgetLine.period=None`** (cf. docstring du
modele) : le rapport d'ecart compare alors le montant budgete (lu comme un
total annuel) au reel CUMULE SUR TOUT L'EXERCICE du budget, sans le repartir
au prorata des periodes — un lissage mensuel automatique serait une
fonctionnalite distincte, non demandee par le plan."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccAnalyticLine,
    AccBudget,
    AccBudgetLine,
    AccFiscalYear,
    AccMove,
    AccMoveLine,
    AccPeriod,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import pending_for_object, request_approval
from apps.core.services.role_hierarchy import superieur_de
from apps.core.services.sequences import next_reference

#: Nom de LA regle d'approbation budgetaire, nomme une fois.
RULE_NAME_APPROBATION = "accounting.budget.approval"

#: Meme delai d'escalade que les paliers de facture : le cahier n'en fixe
#: aucun, et deux valeurs differentes pour la meme organisation seraient une
#: divergence sans motif.
DELAI_ESCALADE = dt.timedelta(days=2)


def create_budget(*, tenant: Tenant, fiscal_year: AccFiscalYear, name: str) -> AccBudget:
    """Cree un budget en `state="draft"`. Reference sequencee par
    tenant/exercice, meme patron que `AccAsset`/`AccProvision` (A10)."""
    reference = next_reference(tenant, "BUD", fiscal_year.date_start.year)
    return AccBudget.objects.create(
        tenant=tenant,
        fiscal_year=fiscal_year,
        name=name,
        reference=reference,
        state=AccBudget.STATE_DRAFT,
    )


def add_budget_line(
    budget: AccBudget,
    *,
    account: AccAccount,
    budgeted_amount_mga: Decimal,
    period: AccPeriod | None = None,
    analytic_account: AccAnalyticAccount | None = None,
) -> AccBudgetLine:
    """Ajoute une ligne a un budget en brouillon. Refuse (`ValidationError`)
    si `budget.state != "draft"` — cf. docstring de module : une revision
    d'un budget deja approuve cree un nouveau budget, ne modifie jamais
    celui-ci sur place."""
    if budget.state != AccBudget.STATE_DRAFT:
        raise ValidationError(
            _(
                "Impossible d'ajouter une ligne a un budget déjà approuve : "
                "creer un nouveau budget pour toute revision."
            )
        )
    return AccBudgetLine.objects.create(
        tenant=budget.tenant,
        budget=budget,
        account=account,
        period=period,
        analytic_account=analytic_account,
        budgeted_amount_mga=budgeted_amount_mga,
    )


def approve_budget(budget: AccBudget) -> AccBudget:
    """Transition `draft -> approved`. Refuse une double approbation."""
    if budget.state != AccBudget.STATE_DRAFT:
        raise ValidationError(_("Ce budget est déjà approuvé."))
    budget.state = AccBudget.STATE_APPROVED
    budget.save(update_fields=["state"])
    return budget


def ensure_budget_approval_rule(tenant: Tenant) -> ApprovalRule:
    """La regle d'approbation budgetaire de cette societe, creee au besoin.

    **Approuver un budget est une DECISION, pas une saisie.** Le service
    `approve_budget` bascule l'etat et rend le budget immuable — c'est
    exactement le geste que le moteur d'approbation du socle existe pour
    encadrer, et que l'ecran de la piece ne doit pas court-circuiter. La
    regle nomme son approbateur (`direction`) et, comme les paliers de
    facture, son secours par la chaine declaree plutot que par une valeur
    ecrite ici."""
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=ContentType.objects.get_for_model(AccBudget),
        name=RULE_NAME_APPROBATION,
        defaults={
            "approver_role": "direction",
            "fallback_approver_role": superieur_de("direction") or "",
            "escalate_after": DELAI_ESCALADE,
            "condition": {},
        },
    )
    return rule


def request_budget_approval(budget: AccBudget, *, requested_by: User) -> ApprovalRequest:
    """Soumet un budget en brouillon a l'approbation.

    Refuse un budget deja approuve, et refuse une SECONDE demande sur le
    meme budget : sans cette garde, un clic repete remplirait l'ecran « Mes
    validations » de demandes identiques dont une seule a un effet — les
    autres retomberaient sur un budget deja bascule et leveraient."""
    if budget.state != AccBudget.STATE_DRAFT:
        raise ValidationError(_("Ce budget est déjà approuvé."))
    if pending_for_object(budget).exists():
        raise ValidationError(_("Ce budget attend déjà une décision d'approbation."))
    if not budget.lines.exists():
        raise ValidationError(
            _("Un budget sans aucune ligne n'a rien à approuver : ajoutez une ligne d'abord.")
        )
    return request_approval(budget, ensure_budget_approval_rule(budget.tenant), requested_by)


def decide_budget_approval(
    approval_request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> AccBudget | None:
    """Effet metier APRES la decision generique du socle.

    Approuve : le budget bascule reellement. Refuse : il RESTE en brouillon,
    modifiable — un refus n'est pas une annulation, c'est une demande de
    revision, et `add_budget_line` n'accepte qu'un brouillon."""
    del decided_by, comment
    budget = AccBudget.objects.filter(id=approval_request.object_id).first()
    if budget is None or not approved:
        return budget
    if budget.state != AccBudget.STATE_DRAFT:
        return budget
    return approve_budget(budget)


def _ratio_or_none(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Meme garde que `reports.py::_ratio_or_none` (A13) : un budget a
    montant nul (ligne de suivi purement qualitative, ou compte pas encore
    budgete l'annee precedente) ne doit jamais faire lever
    `ZeroDivisionError` — `variance_pct` renvoie `None` dans ce cas plutot
    qu'une erreur applicative. Reimplementee ici plutot qu'importee de
    `reports.py` (fonction privee `_`-prefixee, non exposee) : les deux
    fichiers `services/` (rapports vs budgets) sont independants et n'ont
    sinon aucune raison de s'importer l'un l'autre pour un garde-fou de
    3 lignes — cf. rapport de l'utilisateur : "reuse si importable, sinon
    mirror inline"."""
    if denominator == 0:
        return None
    return numerator / denominator


def _actual_amount(line: AccBudgetLine) -> Decimal:
    """Montant reel pour une ligne de budget, dans le sens NATUREL du type
    de compte (`_sum_natural` de `reports.py` : un compte de charge est lu
    en solde debiteur, un compte de produit en solde crediteur), filtre sur
    les ecritures PUBLIEES de la meme periode (si la ligne en specifie une)
    ou de tout l'exercice du budget sinon (cf. docstring de module), et sur
    le meme axe analytique si specifie (jointure `AccAnalyticLine` -> vers
    sa `move_line`, meme patron que `reports.py::analytical_income_statement`
    A13)."""
    natural = "credit" if line.account.type == AccAccount.TYPE_INCOME else "debit"

    if line.analytic_account_id is not None:
        filters: dict[str, Any] = {
            "analytic_account": line.analytic_account,
            "move_line__account": line.account,
            "move_line__move__state": AccMove.STATE_POSTED,
        }
        if line.period_id is not None:
            filters["move_line__move__period"] = line.period
        else:
            filters["move_line__move__period__fiscal_year"] = line.budget.fiscal_year
        totals = AccAnalyticLine.objects.filter(**filters).aggregate(total=Sum("amount"))
        # `AccAnalyticLine.amount` est toujours POSITIF (`debit or credit`,
        # cf. `services/analytics.py::record_analytic_lines`) : pas de solde
        # net debit-credit possible ici, seule une somme directe des
        # montants materialises. Meme simplification que
        # `reports.py::analytical_income_statement` (A13), qui somme "produits"/
        # "charges" de la meme facon sans netter une contre-passation
        # eventuelle sur le meme compte/axe — reprise ici a l'identique par
        # coherence, pas une nouvelle approximation introduite par A14.
        return totals["total"] or Decimal(0)

    move_line_filters: dict[str, Any] = {
        "account": line.account,
        "move__state": AccMove.STATE_POSTED,
    }
    if line.period_id is not None:
        move_line_filters["move__period"] = line.period
    else:
        move_line_filters["move__period__fiscal_year"] = line.budget.fiscal_year

    totals = AccMoveLine.objects.filter(**move_line_filters).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    debit = totals["debit"] or Decimal(0)
    credit = totals["credit"] or Decimal(0)
    return (credit - debit) if natural == "credit" else (debit - credit)


def budget_variance_report(budget: AccBudget) -> list[dict[str, Any]]:
    """Compare, pour chaque `AccBudgetLine` du budget, le montant reel
    (`_actual_amount`, sens naturel du compte) au montant budgete. Renvoie
    une ligne de rapport par `AccBudgetLine`, dans l'ordre `account__code`
    puis `period__code` pour un rendu stable."""
    lines = budget.lines.select_related("account", "period", "analytic_account").order_by(
        "account__code", "period__code"
    )
    rows: list[dict[str, Any]] = []
    for line in lines:
        actual = _actual_amount(line)
        variance = actual - line.budgeted_amount_mga
        rows.append(
            {
                "account_code": line.account.code,
                "account_name": line.account.name,
                "period_label": line.period.code if line.period else None,
                "analytic_account_label": (
                    str(line.analytic_account) if line.analytic_account else None
                ),
                "budgeted_amount_mga": line.budgeted_amount_mga,
                "actual_amount_mga": actual,
                "variance_mga": variance,
                "variance_pct": _ratio_or_none(variance, line.budgeted_amount_mga),
            }
        )
    return rows
