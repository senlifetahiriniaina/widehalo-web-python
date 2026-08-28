"""Ecrans d'import comptable/caisse (session HTMX, jamais l'API JWT en
interne — meme discipline que le reste des ecrans `accounting`). Regroupes
sous le hub "Parametres" (cf. `views_config.py`) plutot que sous le prefixe
transactionnel `/accounting/`, coherent avec le placement deja acte des
autres ecrans de configuration."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccImportBatch, AccImportRow
from apps.accounting.services.cash_journal_import import (
    import_cash_journal_xlsx,
    resolve_import_row,
)
from apps.accounting.services.chart_of_accounts_import import import_chart_of_accounts_xlsx
from apps.core.views.tenant_web import resolve_tenant


@login_required
def imports_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    batches = AccImportBatch.objects.filter(tenant=tenant).order_by("-created_at")[:20]
    return render(request, "accounting/imports/index.html", {"batches": batches})


@login_required
def imports_chart_of_accounts(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_chart_of_accounts_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    return render(
        request,
        "accounting/imports/chart_of_accounts.html",
        {"summary": summary, "error": error},
    )


@login_required
def imports_cash_journal(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_cash_journal_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    return render(
        request,
        "accounting/imports/cash_journal.html",
        {"summary": summary, "error": error},
    )


@login_required
def imports_cash_journal_batch_detail(request: HttpRequest, batch_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    batch = get_object_or_404(AccImportBatch, tenant=tenant, id=batch_id)
    rows = batch.rows.order_by("row_number")
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code")
    return render(
        request,
        "accounting/imports/cash_journal_batch_detail.html",
        {"batch": batch, "rows": rows, "accounts": accounts},
    )


@login_required
def imports_cash_journal_row_resolve(request: HttpRequest, row_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    row = get_object_or_404(AccImportRow, tenant=tenant, id=row_id)

    if request.method == "POST":
        if request.POST.get("discard"):
            resolve_import_row(row, discard=True)
        else:
            account_id = request.POST.get("account_id") or None
            account = (
                AccAccount.objects.filter(tenant=tenant, id=account_id).first()
                if account_id
                else None
            )
            resolve_import_row(row, account=account)

    return redirect("accounting:imports_cash_journal_batch_detail", batch_id=row.batch_id)
