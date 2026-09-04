"""Ecrans HTMX minimaux du module `financing` : liste/creation de dossier de
financement, detail avec plan de financement + garanties + soumission/
decision (FIN1/FIN2), liste/detail CREDOC avec transitions (FIN3). Meme
patron que `apps.strategy.views` : chaque vue appelle directement les
fonctions de service, jamais l'API ninja."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.financing.models import FinCredoc, FinGuarantee, FinLoanApplication
from apps.financing.services.credoc import (
    build_dossier_timeline,
    close_credoc,
    create_credoc,
    credoc_fx_variance,
    open_credoc,
    pay_credoc,
    receive_documents,
)
from apps.financing.services.guarantees import add_guarantee, check_guarantee_coverage
from apps.financing.services.loan_applications import (
    add_financing_plan_line,
    create_loan_application,
    decide_application,
    financing_plan_total,
    submit_application,
)

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="type", label="Type"),
    Column(key="state", label="Statut", searchable=False),
    Column(key="amount_requested_mga", label="Montant demande", searchable=False),
]


@login_required
def loan_application_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    queryset = FinLoanApplication.objects.filter(tenant=tenant, is_active=True)
    return smart_table_response(
        request,
        table_key="financing.loan_applications",
        columns=COLUMNS,
        queryset=queryset,
        page_template="financing/list.html",
        page_context={"row_url_name": "financing:detail"},
    )


@login_required
def loan_application_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None
    if request.method == "POST":
        try:
            application = create_loan_application(
                tenant,
                type=request.POST.get("type", ""),
                amount_requested_mga=Decimal(request.POST.get("amount_requested_mga", "0")),
                duration_months=int(request.POST.get("duration_months", "0")),
                purpose=request.POST.get("purpose", ""),
                bank_name=request.POST.get("bank_name", ""),
            )
            return redirect("financing:detail", application_id=application.id)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
    return render(
        request,
        "financing/create.html",
        {"error": error, "types": FinLoanApplication.LOAN_TYPE_CHOICES},
    )


@login_required
def loan_application_detail(request: HttpRequest, application_id: str) -> HttpResponse:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_line":
                add_financing_plan_line(
                    application,
                    source=request.POST.get("source", ""),
                    amount_mga=Decimal(request.POST.get("amount_mga", "0")),
                    label=request.POST.get("label", ""),
                )
            elif action == "submit":
                submit_application(application)
            elif action == "decide":
                decide_application(
                    application,
                    accepted=request.POST.get("decision") == "accepted",
                    rejection_reason=request.POST.get("rejection_reason", ""),
                )
            elif action == "add_guarantee":
                add_guarantee(
                    application,
                    type=request.POST.get("type", ""),
                    estimated_value_mga=Decimal(request.POST.get("estimated_value_mga", "0")),
                    asset_description=request.POST.get("asset_description", ""),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
        application.refresh_from_db()

    lines = application.financing_plan_lines.filter(is_active=True)
    guarantees = application.guarantees.filter(is_active=True)
    return render(
        request,
        "financing/detail.html",
        {
            "application": application,
            "lines": lines,
            "total": financing_plan_total(application),
            "guarantees": guarantees,
            "guarantee_types": FinGuarantee.GUARANTEE_TYPE_CHOICES,
            "coverage": check_guarantee_coverage(application),
            "error": error,
        },
    )


CREDOC_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="bank", label="Banque"),
    Column(key="state", label="Statut", searchable=False),
    Column(key="amount_mga", label="Montant", searchable=False),
]

# B2 : chaque transition CREDOC exige desormais un motif obligatoire
# (`reason`, cf. `services/credoc.py`) — meme patron `post.get("reason", "")`
# que `apps.purchase.views._ORDER_ACTIONS` pour `cancel`/`open_dispute`.
_CREDOC_TRANSITIONS = {
    "open": lambda credoc, user, post: open_credoc(credoc, user, reason=post.get("reason", "")),
    "receive_documents": lambda credoc, user, post: receive_documents(
        credoc, user, reason=post.get("reason", "")
    ),
    "pay": lambda credoc, user, post: pay_credoc(credoc, user, reason=post.get("reason", "")),
    "close": lambda credoc, user, post: close_credoc(credoc, user, reason=post.get("reason", "")),
}


@login_required
def credoc_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    queryset = FinCredoc.objects.filter(tenant=tenant, is_active=True)
    return smart_table_response(
        request,
        table_key="financing.credocs",
        columns=CREDOC_COLUMNS,
        queryset=queryset,
        page_template="financing/credoc_list.html",
        page_context={"row_url_name": "financing:credoc-detail"},
    )


@login_required
def credoc_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None
    if request.method == "POST":
        try:
            amount_foreign_raw = request.POST.get("amount_foreign", "").strip()
            credoc = create_credoc(
                tenant,
                purchase_order_id=request.POST.get("purchase_order_id", ""),
                bank=request.POST.get("bank", ""),
                beneficiary=request.POST.get("beneficiary", ""),
                amount_mga=Decimal(request.POST.get("amount_mga", "0")),
                validity_date=dt.date.fromisoformat(request.POST.get("validity_date", "")),
                currency=request.POST.get("currency", "MGA") or "MGA",
                amount_foreign=Decimal(amount_foreign_raw) if amount_foreign_raw else None,
            )
            return redirect("financing:credoc-detail", credoc_id=credoc.id)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
    return render(request, "financing/credoc_create.html", {"error": error})


@login_required
def credoc_detail(request: HttpRequest, credoc_id: str) -> HttpResponse:
    credoc = get_object_or_404(FinCredoc, id=credoc_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        transition_fn = _CREDOC_TRANSITIONS.get(action or "")
        if transition_fn is not None:
            try:
                transition_fn(credoc, cast(User, request.user), request.POST)
            except (ValidationError, TransitionPermissionError) as exc:
                error = str(exc)
            credoc.refresh_from_db()

    return render(
        request,
        "financing/credoc_detail.html",
        {"credoc": credoc, "error": error, "fx_variance": credoc_fx_variance(credoc)},
    )


@login_required
def credoc_dossier_timeline(request: HttpRequest, credoc_id: str) -> HttpResponse:
    """B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué", cf.
    plan) : écran composite EN LECTURE SEULE — aucune action de transition
    ici, uniquement `build_dossier_timeline` (`services/credoc.py`), qui
    agrège via les `services.public` de `purchase`/`logistics` (jamais un
    accès direct à leurs modèles, règle de couplage n°1)."""
    credoc = get_object_or_404(FinCredoc, id=credoc_id)
    return render(
        request,
        "financing/credoc_dossier_timeline.html",
        {"credoc": credoc, "dossier": build_dossier_timeline(credoc)},
    )
