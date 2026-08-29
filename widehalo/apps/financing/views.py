"""Ecrans HTMX minimaux du module `financing` (FIN1) : liste/creation de
dossier de financement, detail avec plan de financement + soumission/
decision. Meme patron que `apps.strategy.views` : chaque vue appelle
directement les fonctions de service, jamais l'API ninja."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.financing.models import FinLoanApplication
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
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
        application.refresh_from_db()

    lines = application.financing_plan_lines.filter(is_active=True)
    return render(
        request,
        "financing/detail.html",
        {
            "application": application,
            "lines": lines,
            "total": financing_plan_total(application),
            "error": error,
        },
    )
