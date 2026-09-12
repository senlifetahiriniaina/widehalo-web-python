"""G-2 — les budgets, et leur approbation par le moteur du socle.

**Ce que la mesure a trouve.** `services/budgets.py` sait creer un budget,
lui ajouter des lignes, le rendre immuable a l'approbation et produire un
rapport d'ecart reel/budgete dans le sens naturel de chaque compte. Rien de
tout cela n'etait atteignable : `AccBudget` et `AccBudgetLine`
n'apparaissaient dans aucun gabarit.

**L'approbation ne se fait pas au bouton, et c'est le point du lot.**
`approve_budget` bascule l'etat et FIGE le budget — un geste de cette
portee est exactement ce que le moteur d'approbation du socle existe pour
encadrer. L'ecran ne l'appelle donc jamais directement : il SOUMET
(`request_budget_approval`), la demande apparait dans « Mes validations »
du role approbateur, et c'est sa decision qui bascule le budget par
`decide_and_propagate`. La regle posee en D-B vaut ici a l'identique — *un
moteur d'approbation sans ecran de decision bloque l'operation qu'il
protege* —, et sa reciproque aussi : une transition d'approbation qu'un
ecran declenche seul contourne le moteur qui devait la gouverner.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccBudget,
    AccFiscalYear,
    AccPeriod,
)
from apps.accounting.services.budgets import (
    add_budget_line,
    budget_variance_report,
    create_budget,
    request_budget_approval,
)
from apps.core.models.user import User
from apps.core.services.approvals import pending_for_object
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

BUDGET_COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="name", label=_("Libellé")),
    Column(key="fiscal_year", label=_("Exercice"), search_key="fiscal_year__code"),
    Column(key="state", label=_("État")),
]


def _montant(brut: str | None) -> Decimal:
    try:
        return Decimal((brut or "0").replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(_("Montant illisible : %(v)s") % {"v": brut}) from exc


@login_required
@screen_permission("accounting.view_accbudget")
def budget_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accbudget")
        if refus is not None:
            return refus
        try:
            budget = create_budget(
                tenant=tenant,
                fiscal_year=get_object_or_404(
                    AccFiscalYear, id=request.POST.get("fiscal_year_id"), tenant=tenant
                ),
                name=request.POST.get("name", ""),
            )
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            return redirect("accounting:budget_detail", budget_id=budget.id)

    return smart_table_response(
        request,
        table_key="accounting.budgets",
        columns=BUDGET_COLUMNS,
        queryset=AccBudget.objects.filter(tenant=tenant).select_related("fiscal_year"),
        page_template="accounting/budgets.html",
        page_context={
            "row_url_name": "accounting:budget_detail",
            "exercices": AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start"),
            "error": erreur,
        },
    )


@login_required
@screen_permission("accounting.view_accbudget")
def budget_detail(request: HttpRequest, budget_id: Any) -> HttpResponse:
    tenant = resolve_tenant(request)
    budget = get_object_or_404(AccBudget, id=budget_id, tenant=tenant)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_accbudget")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        try:
            if action == "add_line":
                periode_id = request.POST.get("period_id") or None
                analytique_id = request.POST.get("analytic_account_id") or None
                add_budget_line(
                    budget,
                    account=get_object_or_404(
                        AccAccount, id=request.POST.get("account_id"), tenant=tenant
                    ),
                    budgeted_amount_mga=_montant(request.POST.get("budgeted_amount_mga")),
                    period=(
                        get_object_or_404(AccPeriod, id=periode_id, fiscal_year=budget.fiscal_year)
                        if periode_id
                        else None
                    ),
                    analytic_account=(
                        get_object_or_404(AccAnalyticAccount, id=analytique_id, tenant=tenant)
                        if analytique_id
                        else None
                    ),
                )
            elif action == "request_approval":
                request_budget_approval(budget, requested_by=cast(User, request.user))
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            return redirect("accounting:budget_detail", budget_id=budget.id)

    return render(
        request,
        "accounting/budget_detail.html",
        {
            "budget": budget,
            "ecarts": budget_variance_report(budget),
            # Le rappel sur la fiche : sans lui, celui qui consulte un budget
            # qui refuse de basculer doit deviner pourquoi (meme regle qu'en
            # D-B sur la facture).
            "demandes": pending_for_object(budget),
            "comptes": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
            "periodes": AccPeriod.objects.filter(fiscal_year=budget.fiscal_year).order_by("code"),
            "axes": AccAnalyticAccount.objects.filter(tenant=tenant).order_by("code"),
            "error": erreur,
        },
    )
