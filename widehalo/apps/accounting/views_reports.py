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
from apps.core.report_formats import parse_report_format
from apps.core.services.permissions import screen_forbidden, screen_permission
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
@screen_permission("accounting.view_accmove")
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
@screen_permission("accounting.view_accaccount")
def trial_balance_download(request: HttpRequest) -> HttpResponse:
    fiscal_year = get_object_or_404(AccFiscalYear, id=request.GET.get("fiscal_year_id"))
    format = parse_report_format(request.GET.get("format"))
    rows = trial_balance(fiscal_year)
    data = rows_to_bytes(rows, ["code", "name", "debit", "credit", "balance"], format=format)
    return _report_response(data, format, "balance-generale")


@login_required
@screen_permission("accounting.view_accaccount")
def general_ledger_download(request: HttpRequest) -> HttpResponse:
    account = get_object_or_404(AccAccount, id=request.GET.get("account_id"))
    fiscal_year = get_object_or_404(AccFiscalYear, id=request.GET.get("fiscal_year_id"))
    format = parse_report_format(request.GET.get("format"))
    rows = general_ledger(account, fiscal_year)
    data = rows_to_bytes(rows, ["date", "reference", "label", "debit", "credit"], format=format)
    return _report_response(data, format, "grand-livre")


@login_required
@screen_permission("accounting.view_accjournal")
def journal_report_download(request: HttpRequest) -> HttpResponse:
    journal = get_object_or_404(AccJournal, id=request.GET.get("journal_id"))
    fiscal_year = get_object_or_404(AccFiscalYear, id=request.GET.get("fiscal_year_id"))
    format = parse_report_format(request.GET.get("format"))
    rows = journal_report(journal, fiscal_year)
    data = rows_to_bytes(
        rows, ["reference", "date", "account", "label", "debit", "credit"], format=format
    )
    return _report_response(data, format, "journal")


@login_required
@screen_permission("accounting.view_accvatdeclaration")
def vat_declaration_screen(request: HttpRequest) -> HttpResponse:
    """ACC-6 — la declaration de TVA d'une periode, vue par le comptable.

    **L'ecran est ce qui rend le critere utilisable.** Le rapprochement a
    l'ariari pres et l'etat justificatif ligne a ligne existent en service
    et en API depuis ce lot ; c'est ici qu'un comptable les LIT — et
    surtout, qu'il voit d'ou vient l'ecart avant de deposer, plutot que de
    le decouvrir au controle.

    La periode est choisie explicitement (`?period_id=`) et non devinee
    d'apres la date du jour : une declaration se prepare apres la cloture
    de la periode qu'elle couvre, jamais pendant."""
    from apps.accounting.models import AccPeriod
    from apps.accounting.services.vat_declaration import (
        declaration_for,
    )

    tenant = resolve_tenant(request)
    periodes = AccPeriod.objects.filter(tenant=tenant).order_by("-date_start")
    period_id = request.GET.get("period_id", "")
    periode = periodes.filter(id=period_id).first() if period_id else periodes.first()

    if periode is None:
        return render(
            request,
            "accounting/vat_declaration.html",
            {"periodes": periodes, "periode": None, "declaration": None},
        )

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accvatdeclaration")
        if refus is not None:
            return refus

    if request.method == "POST" and request.POST.get("action") == "file":
        from django.core.exceptions import ValidationError

        from apps.accounting.services.vat_declaration import (
            declaration_for,
            file_vat_declaration,
        )

        try:
            file_vat_declaration(declaration_for(periode))
        except ValidationError as exc:
            return render(
                request,
                "accounting/vat_declaration.html",
                _vat_context(periodes, periode, erreur="; ".join(exc.messages)),
            )

    return render(request, "accounting/vat_declaration.html", _vat_context(periodes, periode))


def _vat_context(periodes: object, periode: object, *, erreur: str = "") -> dict[str, object]:
    from apps.accounting.services.vat_declaration import (
        declaration_for,
        unjustified_book_lines,
        vat_declaration_detail,
    )

    declaration = declaration_for(periode)  # type: ignore[arg-type]
    return {
        "periodes": periodes,
        "periode": periode,
        "declaration": declaration,
        "lignes": declaration.lines.select_related("tax").all(),
        "detail": vat_declaration_detail(declaration),
        "non_justifiees": unjustified_book_lines(declaration),
        "erreur": erreur,
    }
