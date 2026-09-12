"""G-4 — les coûts d'approche et la déclaration DCOM.

**Deux chaînes complètes sans aucune porte.** `landed_costs` sait composer
un lot d'importation, y répartir les frais d'approche selon trois clés et
répercuter le coût débarqué sur la valorisation de stock ; `dcom` sait
produire la déclaration du droit de communication à partir du grand livre.
Ni `AccLandedCostBatch`, ni `AccLandedCostLine`, ni `AccLandedCostComponent`,
ni `AccDcomDeclaration` n'apparaissaient dans un gabarit.

**Finaliser un lot n'est pas un enregistrement de plus.** `finalize_batch`
répercute réellement le coût alloué sur la valorisation de chaque variante
concernée : l'écran le dit avant de proposer le bouton, et le rapport
d'allocation est lisible AVANT la finalisation — comme le plan
d'amortissement se relit avant d'être engagé.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import (
    AccAccount,
    AccDcomDeclaration,
    AccFiscalYear,
    AccLandedCostBatch,
)
from apps.accounting.services.dcom import generate_dcom_declaration
from apps.accounting.services.landed_costs import (
    add_cost_component,
    add_landed_cost_line,
    create_landed_cost_batch,
    finalize_batch,
    landed_cost_report,
)
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.partners.services.public import get_partner_display_names

LANDED_COST_COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="label", label=_("Libellé")),
    Column(key="date", label=_("Date"), searchable=False),
    Column(key="allocation_method", label=_("Répartition")),
    Column(
        key="total_purchase_value_mga", label=_("Valeur d'achat"), searchable=False, format="mga"
    ),
    Column(key="state", label=_("État")),
]


def _montant(brut: str | None) -> Decimal:
    try:
        return Decimal((brut or "0").replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(_("Montant illisible : %(v)s") % {"v": brut}) from exc


def _date(brut: str | None) -> dt.date:
    try:
        return dt.date.fromisoformat(brut or "")
    except ValueError as exc:
        raise ValidationError(_("Date illisible : %(v)s") % {"v": brut}) from exc


def _messages(exc: ValidationError) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


@login_required
@screen_permission("accounting.view_acclandedcostbatch")
def landed_cost_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_acclandedcostbatch")
        if refus is not None:
            return refus
        try:
            lot = create_landed_cost_batch(
                tenant=tenant,
                label=request.POST.get("label", ""),
                date=_date(request.POST.get("date")),
                allocation_method=request.POST.get(
                    "allocation_method", AccLandedCostBatch.METHOD_BY_VALUE
                ),
            )
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect("accounting:landed_cost_detail", batch_id=lot.id)

    return smart_table_response(
        request,
        table_key="accounting.landed_costs",
        columns=LANDED_COST_COLUMNS,
        queryset=AccLandedCostBatch.objects.filter(tenant=tenant),
        page_template="accounting/landed_costs.html",
        page_context={
            "row_url_name": "accounting:landed_cost_detail",
            "methodes": AccLandedCostBatch.METHOD_CHOICES,
            "error": erreur,
        },
    )


@login_required
@screen_permission("accounting.view_acclandedcostbatch")
def landed_cost_detail(request: HttpRequest, batch_id: Any) -> HttpResponse:
    tenant = resolve_tenant(request)
    lot = get_object_or_404(AccLandedCostBatch, id=batch_id, tenant=tenant)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_acclandedcostbatch")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        try:
            if action == "add_line":
                poids = request.POST.get("weight_kg") or ""
                add_landed_cost_line(
                    lot,
                    description=request.POST.get("description", ""),
                    qty=_montant(request.POST.get("qty")),
                    purchase_value_mga=_montant(request.POST.get("purchase_value_mga")),
                    weight_kg=_montant(poids) if poids else None,
                )
            elif action == "add_component":
                compte_id = request.POST.get("account_id") or None
                add_cost_component(
                    lot,
                    label=request.POST.get("component_label", ""),
                    amount_mga=_montant(request.POST.get("amount_mga")),
                    account=(
                        get_object_or_404(AccAccount, id=compte_id, tenant=tenant)
                        if compte_id
                        else None
                    ),
                )
            elif action == "finalize":
                finalize_batch(lot)
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect("accounting:landed_cost_detail", batch_id=lot.id)

    # Le rapport est calculable dans les deux états : une répartition se
    # relit AVANT d'être engagée sur la valorisation de stock.
    try:
        rapport = landed_cost_report(lot)
    except ValidationError as exc:
        rapport = []
        erreur = erreur or _messages(exc)

    return render(
        request,
        "accounting/landed_cost_detail.html",
        {
            "lot": lot,
            "rapport": rapport,
            "composants": lot.cost_components.all().order_by("label"),
            "comptes": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
            "error": erreur,
        },
    )


@login_required
@screen_permission("accounting.view_accdcomdeclaration")
def dcom_screen(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accdcomdeclaration")
        if refus is not None:
            return refus
        try:
            declaration = generate_dcom_declaration(
                get_object_or_404(
                    AccFiscalYear, id=request.POST.get("fiscal_year_id"), tenant=tenant
                )
            )
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect(f"{request.path}?fiscal_year_id={declaration.fiscal_year_id}")

    exercices = list(AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start"))
    exercice_id = request.GET.get("fiscal_year_id") or (str(exercices[0].id) if exercices else "")
    # **Une societe sans exercice rendait 500.** `filter(fiscal_year_id="")`
    # fait lever `ValidationError: n'est pas un UUID valide`, qu'aucun
    # gestionnaire ne rattrape — meme famille que les identifiants non
    # types fermes en T4bis, sur la valeur VIDE cette fois. Trouve par le
    # crawler d'ecrans, jamais par la relecture : c'est exactement le cas
    # d'une societe neuve, le premier jour.
    declaration = (
        AccDcomDeclaration.objects.filter(tenant=tenant, fiscal_year_id=exercice_id).first()
        if exercice_id
        else None
    )
    lignes = list(declaration.lines.all().order_by("-amount_mga")) if declaration else []
    noms = get_partner_display_names({ligne.partner_id for ligne in lignes})
    for ligne in lignes:
        ligne.partner_display = noms.get(str(ligne.partner_id), "")

    return render(
        request,
        "accounting/dcom.html",
        {
            "exercices": exercices,
            "exercice_id": exercice_id,
            "declaration": declaration,
            "lignes": lignes,
            "error": erreur,
        },
    )
