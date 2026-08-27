"""Ecrans HTMX minimaux du module `accounting` (verification des 14
couches, U1) : liste des factures client, detail avec bandeau de workflow
+ panneau lateral (audit/documents), formulaire de creation. Meme patron
que `apps.partners.views` : chaque vue appelle directement les fonctions
de service, jamais l'API ninja, authentification par session."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccPeriod
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    cancel_invoice,
    create_invoice,
    validate_invoice,
)
from apps.core.models.audit import AuditLog
from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="date", label="Date"),
    Column(key="invoice_state", label="Statut"),
    Column(key="total_debit", label="Montant (MGA)", searchable=False),
]


@login_required
def invoice_list(request: HttpRequest) -> HttpResponse:
    queryset = AccMove.objects.filter(move_type=AccMove.TYPE_CUSTOMER_INVOICE, is_active=True)
    return smart_table_response(
        request,
        table_key="accounting.invoices",
        columns=COLUMNS,
        queryset=queryset,
        page_template="accounting/list.html",
        page_context={"row_url_name": "accounting:detail"},
    )


@login_required
def invoice_detail(request: HttpRequest, invoice_id: str) -> HttpResponse:
    invoice = get_object_or_404(AccMove, id=invoice_id, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
    content_type = ContentType.objects.get_for_model(AccMove)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "validate":
                validate_invoice(invoice, user)
            elif action == "cancel":
                cancel_invoice(invoice, user, motif=request.POST.get("motif", ""))
        except (ApprovalRequiredError, ValidationError) as exc:
            error = str(exc)
        else:
            return redirect("accounting:detail", invoice_id=invoice.id)

    uploaded_file = request.FILES.get("document")
    if request.method == "POST" and uploaded_file is not None:
        store_document(
            tenant=invoice.tenant,
            uploaded_file=uploaded_file,
            uploaded_by=user if user.is_authenticated else None,
            content_object=invoice,
        )
        return redirect("accounting:detail", invoice_id=invoice.id)

    audit_entries = AuditLog.objects.filter(
        content_type=content_type, object_id=str(invoice.id)
    ).order_by("-created_at")[:20]
    documents = Document.objects.filter(content_type=content_type, object_id=str(invoice.id))

    return render(
        request,
        "accounting/detail.html",
        {
            "invoice": invoice,
            "lines": invoice.lines.all(),
            "audit_entries": audit_entries,
            "documents": documents,
            "error": error,
        },
    )


@login_required
def invoice_create(request: HttpRequest) -> HttpResponse:
    """Formulaire minimal : une facture a ligne de produit unique (le
    detail multi-lignes reste accessible via l'API pour les besoins
    avances — coherent avec le perimetre "ecran minimal" de cette phase)."""
    tenant = resolve_tenant(request)
    journals = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_SALE)
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            journal = get_object_or_404(AccJournal, id=request.POST.get("journal_id"))
            period = (
                AccPeriod.objects.filter(tenant=tenant, state=AccPeriod.STATE_OPEN)
                .order_by("date_start")
                .first()
            )
            if period is None:
                raise ValidationError(_("Aucune periode ouverte pour cet exercice."))
            receivable_account = get_object_or_404(
                AccAccount, id=request.POST.get("receivable_account_id")
            )
            income_account = get_object_or_404(AccAccount, id=request.POST.get("income_account_id"))
            amount = Decimal(request.POST.get("amount") or "0")
            invoice = create_invoice(
                tenant=tenant,
                journal=journal,
                period=period,
                date=date.fromisoformat(request.POST.get("date") or date.today().isoformat()),
                partner_id=None,
                receivable_account=receivable_account,
                income_lines=[
                    {
                        "account": income_account,
                        "amount": amount,
                        "label": request.POST.get("label", ""),
                    }
                ],
            )
        except (ValidationError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("accounting:detail", invoice_id=invoice.id)

    return render(
        request,
        "accounting/create.html",
        {"journals": journals, "accounts": accounts, "error": error, "today": date.today()},
    )
