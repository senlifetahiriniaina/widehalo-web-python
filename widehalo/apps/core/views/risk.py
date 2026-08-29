"""Ecran generique « Registre des risques » (RSK1-2) — liste (SmartTable) +
detail, rattachable depuis n'importe quel ecran de detail d'un autre module
via le mecanisme content_type/object_id (l'integration effective dans des
ecrans d'autres modules — ex. un bouton "Signaler un risque" sur une fiche
`PurOrder` — est un travail futur, hors perimetre RSK1-2 : cf. plan)."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.models.risk import CATEGORY_CHOICES, STATUS_CHOICES, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.risk import close_risk_item, create_risk_item, update_risk_item
from apps.core.views.smart_table import Column, smart_table_response

COLUMNS = [
    Column(key="category", label="Categorie"),
    Column(key="likelihood", label="Probabilite", searchable=False),
    Column(key="impact", label="Impact", searchable=False),
    Column(key="score", label="Score", searchable=False),
    Column(key="status", label="Statut"),
]


def _visible_queryset(user: User):
    """Meme regle de visibilite que `apps.core.api_risk` (cf. sa
    docstring) : `core.change_riskitem` (admin/direction) -> tout le
    tenant, sinon uniquement les risques dont l'utilisateur est owner."""
    queryset = RiskItem.objects.all()
    if user.has_perm("core.change_riskitem"):
        return queryset
    return queryset.filter(owner=user)


def _resolve_tenant(request: HttpRequest) -> Tenant:
    tenant_id = request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""
    return Tenant.objects.get(id=tenant_id)


@login_required
def risk_list(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    queryset = _visible_queryset(user)
    return smart_table_response(
        request,
        table_key="core.risks",
        columns=COLUMNS,
        queryset=queryset,
        page_template="risk/list.html",
    )


@login_required
def risk_create(request: HttpRequest) -> HttpResponse:
    """Composant de signalement generique (bouton "Signaler un risque") —
    ecran autonome dans ce lot ; le mecanisme (`create_risk_item`) est
    concu pour etre reutilise depuis un futur ecran de detail d'un autre
    module (passage d'un `content_object`), non branche ici (hors
    perimetre RSK1-2, cf. plan)."""
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        try:
            likelihood = int(request.POST.get("likelihood", "0"))
            impact = int(request.POST.get("impact", "0"))
            if not (1 <= likelihood <= 5) or not (1 <= impact <= 5):
                raise ValueError
        except ValueError:
            error = _("Probabilite et impact doivent etre des entiers entre 1 et 5.")
        else:
            risk_item = create_risk_item(
                tenant=_resolve_tenant(request),
                category=request.POST.get("category", ""),
                likelihood=likelihood,
                impact=impact,
                owner=user,
                mitigation_plan=request.POST.get("mitigation_plan", ""),
            )
            return redirect("risk_detail", risk_id=risk_item.id)

    return render(
        request,
        "risk/create.html",
        {"error": error, "category_choices": CATEGORY_CHOICES},
    )


@login_required
def risk_detail(request: HttpRequest, risk_id: str) -> HttpResponse:
    user = cast(User, request.user)
    risk_item = get_object_or_404(_visible_queryset(user), id=risk_id)

    if request.method == "POST":
        action = request.POST.get("action", "update")
        if action == "close":
            close_risk_item(risk_item, closed_by=user)
        else:
            update_risk_item(
                risk_item,
                updated_by=user,
                mitigation_plan=request.POST.get("mitigation_plan", risk_item.mitigation_plan),
            )
        return redirect("risks:detail", risk_id=risk_item.id)

    return render(
        request,
        "risk/detail.html",
        {"risk_item": risk_item, "status_choices": STATUS_CHOICES},
    )
