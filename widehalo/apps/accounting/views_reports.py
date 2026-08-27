"""Ecran de rapports du module `accounting` (U5) : expose en session/HTML
les fonctions de `apps.accounting.services.reports` — jusqu'ici accessibles
uniquement via l'API ninja (authentification JWT), donc injoignables depuis
une session navigateur classique. Meme patron que `apps.accounting.views` :
chaque vue appelle directement les fonctions de service, jamais l'API
ninja."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal
from apps.accounting.services.reports import (
    general_ledger,
    journal_report,
    rows_to_bytes,
    trial_balance,
)
from apps.core.views.tenant_web import resolve_tenant

CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _report_response(data: bytes, format: str, filename: str) -> HttpResponse:
    response = HttpResponse(
        data, content_type=CONTENT_TYPES.get(format, "application/octet-stream")
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.{format}"'
    return response


@login_required
def reports_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    return render(
        request,
        "accounting/reports.html",
        {
            "fiscal_years": AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start"),
            "accounts": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
            "journals": AccJournal.objects.filter(tenant=tenant).order_by("code"),
        },
    )


@login_required
def trial_balance_download(request: HttpRequest) -> HttpResponse:
    fiscal_year = get_object_or_404(AccFiscalYear, id=request.GET.get("fiscal_year_id"))
    format = request.GET.get("format", "json")
    rows = trial_balance(fiscal_year)
    data = rows_to_bytes(rows, ["code", "name", "debit", "credit", "balance"], format=format)
    return _report_response(data, format, "balance-generale")


@login_required
def general_ledger_download(request: HttpRequest) -> HttpResponse:
    account = get_object_or_404(AccAccount, id=request.GET.get("account_id"))
    fiscal_year = get_object_or_404(AccFiscalYear, id=request.GET.get("fiscal_year_id"))
    format = request.GET.get("format", "json")
    rows = general_ledger(account, fiscal_year)
    data = rows_to_bytes(rows, ["date", "reference", "label", "debit", "credit"], format=format)
    return _report_response(data, format, "grand-livre")


@login_required
def journal_report_download(request: HttpRequest) -> HttpResponse:
    journal = get_object_or_404(AccJournal, id=request.GET.get("journal_id"))
    fiscal_year = get_object_or_404(AccFiscalYear, id=request.GET.get("fiscal_year_id"))
    format = request.GET.get("format", "json")
    rows = journal_report(journal, fiscal_year)
    data = rows_to_bytes(
        rows, ["reference", "date", "account", "label", "debit", "credit"], format=format
    )
    return _report_response(data, format, "journal")
