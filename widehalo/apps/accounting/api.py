from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.accounting.models import (
    AccAccount,
    AccAnalyticPlan,
    AccAsset,
    AccDcomDeclaration,
    AccFiscalYear,
    AccIrcmDeclaration,
    AccJournal,
    AccLocalTax,
    AccMove,
    AccPayment,
    AccPeriod,
    AccProvision,
    AccTaxCalendar,
)
from apps.accounting.services.assets import (
    compute_annual_depreciation,
    dispose_asset,
    record_provision_movement,
    register_asset,
)
from apps.accounting.services.dcom import generate_dcom_declaration
from apps.accounting.services.fiscal_export import export_canevas_notes
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    create_invoice,
    validate_invoice,
)
from apps.accounting.services.ircm import generate_ircm_declaration
from apps.accounting.services.local_tax import record_local_tax
from apps.accounting.services.moves import post_move, reverse_move
from apps.accounting.services.payments import register_payment
from apps.accounting.services.reports import (
    aged_payables,
    aged_receivables,
    analytical_income_statement,
    balance_sheet,
    cash_flow_statement,
    dcom_report,
    equity_variation_statement,
    financial_ratios,
    fixed_asset_annexes,
    general_ledger,
    income_statement,
    income_statement_by_function,
    invoice_pdf,
    journal_report,
    rows_to_bytes,
    trial_balance,
)
from apps.accounting.services.tax_calendar import create_tax_calendar_entry
from apps.accounting.services.tax_returns import generate_liasse_ir, generate_liasse_is
from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission

router = Router(tags=["accounting"])


class InvoiceLineIn(Schema):
    account_id: str
    amount: Decimal
    label: str = ""


class InvoiceIn(Schema):
    journal_id: str
    period_id: str
    date: dt.date
    partner_id: str | None = None
    receivable_account_id: str
    currency: str = "MGA"
    lines: list[InvoiceLineIn]


class TaxCalendarIn(Schema):
    declaration_type: str
    label: str
    due_date: dt.date
    periodicity: str
    is_recurring_template: bool = False


class AssetIn(Schema):
    category: str
    label: str
    account_id: str
    acquisition_date: dt.date
    acquisition_value_mga: Decimal
    depreciation_method: str
    useful_life_years: int
    residual_value_mga: Decimal = Decimal(0)


class AssetDisposeIn(Schema):
    disposal_date: dt.date
    disposal_value_mga: Decimal


class AssetDepreciationComputeIn(Schema):
    fiscal_year_id: str
    post: bool = False
    journal_id: str | None = None
    period_id: str | None = None
    dotation_account_id: str | None = None
    accumulated_depreciation_account_id: str | None = None


class ProvisionIn(Schema):
    nature: str
    account_id: str
    fiscal_year_id: str
    opening_amount_mga: Decimal = Decimal(0)
    dotation_mga: Decimal = Decimal(0)
    reprise_mga: Decimal = Decimal(0)


class DcomGenerateIn(Schema):
    fiscal_year_id: str


class IrcmGenerateIn(Schema):
    fiscal_year_id: str
    rate_pct: Decimal = Decimal("20")


class LocalTaxIn(Schema):
    tax_type: str
    property_label: str
    assessed_value_mga: Decimal
    rate_pct: Decimal
    fiscal_year_id: str


class RegisterPaymentIn(Schema):
    period_id: str
    journal_id: str
    cash_account_id: str
    gain_account_id: str
    loss_account_id: str
    date: dt.date
    amount: Decimal
    method: str
    reference_external: str = ""


def _serialize_move(move: AccMove) -> dict:
    return {
        "id": str(move.id),
        "reference": move.reference,
        "state": move.state,
        "invoice_state": move.invoice_state,
        "move_type": move.move_type,
        "total_debit": str(move.total_debit),
        "total_credit": str(move.total_credit),
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# (le plus haut) et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`). `Router.api_operation` enregistre dans `add_api_operation` la
# fonction qui lui est passee DIRECTEMENT (celle definie juste en dessous
# dans le code), puis la retourne inchangee — donc seul le decorateur le
# plus proche de `def` finit dans la table de routage effectivement
# invoquee a chaque requete. Verifie empiriquement : dans l'ordre inverse,
# `require_permission` ne bloque JAMAIS aucune requete HTTP reelle (mais
# reste visible sur le nom de fonction au niveau module, d'ou le risque de
# le croire actif a la simple lecture du code).
@router.get("/accounting/accounts")
@require_permission("accounting.view_accaccount")
def list_accounts(request):
    return {
        "results": [
            {"id": str(a.id), "code": a.code, "name": a.name, "type": a.type}
            for a in AccAccount.objects.filter(is_active=True).order_by("code")
        ]
    }


@router.get("/accounting/moves")
@require_permission("accounting.view_accmove")
def list_moves(request):
    return {"results": [_serialize_move(m) for m in AccMove.objects.all().order_by("-date")]}


@router.post("/accounting/moves/{move_id}/post")
@require_permission("accounting.change_accmove")
def post_move_endpoint(request, move_id: str):
    move = get_object_or_404(AccMove, id=move_id)
    try:
        posted = post_move(move)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(posted)


@router.post("/accounting/moves/{move_id}/reverse")
@require_permission("accounting.change_accmove")
def reverse_move_endpoint(request, move_id: str, motif: str = ""):
    move = get_object_or_404(AccMove, id=move_id)
    try:
        reversal = reverse_move(move, motif=motif)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(reversal)


@router.get("/accounting/invoices")
@require_permission("accounting.view_accmove")
def list_invoices(request):
    invoices = AccMove.objects.filter(move_type=AccMove.TYPE_CUSTOMER_INVOICE).order_by("-date")
    return {"results": [_serialize_move(i) for i in invoices]}


@router.post("/accounting/invoices")
@require_permission("accounting.add_accmove")
def create_invoice_endpoint(request, payload: InvoiceIn):
    journal = get_object_or_404(AccJournal, id=payload.journal_id)
    period = get_object_or_404(AccPeriod, id=payload.period_id)
    receivable_account = get_object_or_404(AccAccount, id=payload.receivable_account_id)

    income_lines = []
    for line in payload.lines:
        income_lines.append(
            {
                "account": get_object_or_404(AccAccount, id=line.account_id),
                "amount": line.amount,
                "label": line.label,
            }
        )

    invoice = create_invoice(
        tenant=journal.tenant,
        journal=journal,
        period=period,
        date=payload.date,
        partner_id=uuid.UUID(payload.partner_id) if payload.partner_id else None,
        receivable_account=receivable_account,
        income_lines=income_lines,
        currency=payload.currency,
    )
    return _serialize_move(invoice)


@router.post("/accounting/invoices/{invoice_id}/validate")
@require_permission("accounting.validate_accmove")
def validate_invoice_endpoint(request, invoice_id: str, comment: str = ""):
    invoice = get_object_or_404(AccMove, id=invoice_id)
    try:
        validated = validate_invoice(invoice, request.auth, comment=comment)
    except ApprovalRequiredError as exc:
        return JsonResponse({"detail": str(exc), "status": "pending_approval"}, status=202)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_move(validated)


@router.post("/accounting/invoices/{invoice_id}/register-payment")
@require_permission("accounting.change_accmove")
def register_payment_endpoint(request, invoice_id: str, payload: RegisterPaymentIn):
    invoice = get_object_or_404(AccMove, id=invoice_id)
    period = get_object_or_404(AccPeriod, id=payload.period_id)
    journal = get_object_or_404(AccJournal, id=payload.journal_id)
    cash_account = get_object_or_404(AccAccount, id=payload.cash_account_id)
    gain_account = get_object_or_404(AccAccount, id=payload.gain_account_id)
    loss_account = get_object_or_404(AccAccount, id=payload.loss_account_id)

    try:
        payment = register_payment(
            invoice=invoice,
            period=period,
            journal=journal,
            cash_account=cash_account,
            gain_account=gain_account,
            loss_account=loss_account,
            date=payload.date,
            amount=payload.amount,
            method=payload.method,
            reference_external=payload.reference_external,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)

    return {"id": str(payment.id), "reference": payment.reference, "amount": str(payment.amount)}


@router.get("/accounting/invoices/{invoice_id}/pdf")
@require_permission("accounting.view_accmove")
def invoice_pdf_endpoint(request, invoice_id: str):
    invoice = get_object_or_404(AccMove, id=invoice_id)
    pdf_bytes = invoice_pdf(invoice)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{invoice.reference or invoice.id}.pdf"'
    return response


@router.get("/accounting/payments")
@require_permission("accounting.view_accpayment")
def list_payments(request):
    return {
        "results": [
            {"id": str(p.id), "reference": p.reference, "amount": str(p.amount), "state": p.state}
            for p in AccPayment.objects.all().order_by("-date")
        ]
    }


def _serialize_tax_calendar_entry(entry: AccTaxCalendar) -> dict:
    return {
        "id": str(entry.id),
        "declaration_type": entry.declaration_type,
        "label": entry.label,
        "due_date": entry.due_date.isoformat(),
        "periodicity": entry.periodicity,
        "is_recurring_template": entry.is_recurring_template,
    }


@router.get("/accounting/tax-calendar")
@require_permission("accounting.view_acctaxcalendar")
def list_tax_calendar_endpoint(request, declaration_type: str = "", within_days: int | None = None):
    """ACC-CAL1 — liste des echeances fiscales du tenant courant, filtrable
    par `declaration_type` et/ou restreinte aux `within_days` prochains
    jours (memes filtres qu'`upcoming_deadlines`, exposes ici directement
    en requete SQL pour rester coherent avec un tri systematique par
    date)."""
    entries = AccTaxCalendar.objects.all().order_by("due_date")
    if declaration_type:
        entries = entries.filter(declaration_type=declaration_type)
    if within_days is not None:
        today = dt.date.today()
        entries = entries.filter(
            due_date__gte=today, due_date__lte=today + dt.timedelta(days=within_days)
        )
    return {"results": [_serialize_tax_calendar_entry(e) for e in entries]}


@router.post("/accounting/tax-calendar")
@require_permission("accounting.add_acctaxcalendar")
def create_tax_calendar_endpoint(request, payload: TaxCalendarIn):
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    entry = create_tax_calendar_entry(
        tenant=tenant,
        declaration_type=payload.declaration_type,
        label=payload.label,
        due_date=payload.due_date,
        periodicity=payload.periodicity,
        is_recurring_template=payload.is_recurring_template,
    )
    return _serialize_tax_calendar_entry(entry)


@router.get("/accounting/reports/trial-balance")
@require_permission("accounting.view_accaccount")
def trial_balance_endpoint(request, fiscal_year_id: str, format: str = "json"):
    from apps.accounting.models import AccFiscalYear

    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    rows = trial_balance(fiscal_year)
    data = rows_to_bytes(rows, ["code", "name", "debit", "credit", "balance"], format=format)
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return HttpResponse(data, content_type=content_type)


@router.get("/accounting/reports/general-ledger")
@require_permission("accounting.view_accmove")
def general_ledger_endpoint(request, account_id: str, fiscal_year_id: str, format: str = "json"):
    from apps.accounting.models import AccFiscalYear

    account = get_object_or_404(AccAccount, id=account_id)
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    rows = general_ledger(account, fiscal_year)
    data = rows_to_bytes(rows, ["date", "reference", "label", "debit", "credit"], format=format)
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return HttpResponse(data, content_type=content_type)


@router.get("/accounting/reports/journal")
@require_permission("accounting.view_accmove")
def journal_report_endpoint(request, journal_id: str, fiscal_year_id: str, format: str = "json"):
    from apps.accounting.models import AccFiscalYear

    journal = get_object_or_404(AccJournal, id=journal_id)
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    rows = journal_report(journal, fiscal_year)
    data = rows_to_bytes(
        rows, ["reference", "date", "account", "label", "debit", "credit"], format=format
    )
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[format]
    return HttpResponse(data, content_type=content_type)


_REPORT_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _flatten_balance_sheet(data: dict) -> list[dict]:
    """Aplatit `balance_sheet()` en lignes pour l'export CSV/XLSX (le format
    JSON, structure, reste servi directement sans passer par cette fonction)."""
    rows = []
    for section, bucket_key in (("actif", "actif"), ("passif", "passif")):
        for courant, bucket in (("courant", "courant"), ("non_courant", "non_courant")):
            for line in data[bucket_key][bucket]:
                rows.append(
                    {
                        "section": section,
                        "courant": courant,
                        "code": line["code"],
                        "name": line["name"],
                        "amount": line["amount"],
                    }
                )
    return rows


@router.get("/accounting/reports/balance-sheet")
@require_permission("accounting.view_accaccount")
def balance_sheet_endpoint(
    request, fiscal_year_id: str, as_of_date: dt.date | None = None, format: str = "json"
):
    """ACC-BIL — bilan. Reserve OECFM : cf. docstring de
    `services/reports.py::balance_sheet`."""
    from apps.accounting.models import AccFiscalYear

    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    data = balance_sheet(fiscal_year, as_of_date=as_of_date)
    if format == "json":
        return JsonResponse(data)
    rows = _flatten_balance_sheet(data)
    payload = rows_to_bytes(rows, ["section", "courant", "code", "name", "amount"], format=format)
    return HttpResponse(payload, content_type=_REPORT_CONTENT_TYPES[format])


@router.get("/accounting/reports/income-statement")
@require_permission("accounting.view_accaccount")
def income_statement_endpoint(request, fiscal_year_id: str, format: str = "json"):
    """ACC-CR — compte de resultat par nature. Reserve OECFM : cf. docstring
    de `services/reports.py::income_statement`."""
    from apps.accounting.models import AccFiscalYear

    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    rows = income_statement(fiscal_year)
    data = rows_to_bytes(rows, ["poste", "label", "amount"], format=format)
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


@router.get("/accounting/reports/income-statement-by-function")
@require_permission("accounting.view_accaccount")
def income_statement_by_function_endpoint(request, fiscal_year_id: str, format: str = "json"):
    """ACC-CR-FCT — compte de resultat par fonction. Reserve OECFM : cf.
    docstring de `services/reports.py::income_statement_by_function`."""
    from apps.accounting.models import AccFiscalYear

    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    rows = income_statement_by_function(fiscal_year)
    data = rows_to_bytes(rows, ["label", "amount"], format=format)
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


@router.get("/accounting/reports/cash-flow")
@require_permission("accounting.view_accaccount")
def cash_flow_endpoint(request, fiscal_year_id: str, format: str = "json"):
    """ACC-CF — tableau des flux de tresorerie (methode directe). Reserve
    OECFM et choix de methode : cf. docstring de
    `services/reports.py::cash_flow_statement`."""
    from apps.accounting.models import AccFiscalYear

    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    data = cash_flow_statement(fiscal_year)
    if format == "json":
        return JsonResponse(data)
    payload = rows_to_bytes(
        data["lines"], ["date", "reference", "section", "account", "label", "amount"], format=format
    )
    return HttpResponse(payload, content_type=_REPORT_CONTENT_TYPES[format])


@router.get("/accounting/reports/equity-variation")
@require_permission("accounting.view_accaccount")
def equity_variation_endpoint(request, fiscal_year_id: str, format: str = "json"):
    """ACC-VCP — etat de variation des capitaux propres. Simplification V1 :
    cf. docstring de `services/reports.py::equity_variation_statement`."""
    from apps.accounting.models import AccFiscalYear

    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    rows = equity_variation_statement(fiscal_year)
    data = rows_to_bytes(rows, ["code", "name", "opening", "movement", "closing"], format=format)
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


_AGED_BALANCE_FIELDS = [
    "partner_id",
    "moins_d_un_an",
    "un_a_cinq_ans",
    "plus_de_cinq_ans",
    "total",
]


@router.get("/accounting/reports/aged-receivables")
@require_permission("accounting.view_accmove")
def aged_receivables_endpoint(request, as_of_date: dt.date | None = None, format: str = "json"):
    """ACC-AGE-C — balance agee clients."""
    rows = aged_receivables(as_of_date)
    data = rows_to_bytes(rows, _AGED_BALANCE_FIELDS, format=format)
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


@router.get("/accounting/reports/aged-payables")
@require_permission("accounting.view_accmove")
def aged_payables_endpoint(request, as_of_date: dt.date | None = None, format: str = "json"):
    """ACC-AGE-F — balance agee fournisseurs."""
    rows = aged_payables(as_of_date)
    data = rows_to_bytes(rows, _AGED_BALANCE_FIELDS, format=format)
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


# ---------------------------------------------------------------------------
# A13 — Ratios financiers complets (ACC-RATIO1/ACC-RATIO2) et analytique
# (ACC-ANA)
# ---------------------------------------------------------------------------


@router.get("/accounting/reports/financial-ratios")
@require_permission("accounting.view_accaccount")
def financial_ratios_endpoint(request, fiscal_year_id: str):
    """ACC-RATIO1/ACC-RATIO2 — ratios financiers de base plus les 3 piliers
    de l'analyse bancaire locale (FDR/BFR/tresorerie nette). Reserve sur les
    formules approximatives (marge brute, DSO/DPO, rentabilite economique/
    financiere...) : cf. docstring de `services/reports.py::financial_ratios`.

    Pas d'export CSV/XLSX (`rows_to_bytes` attend une liste de lignes
    tabulaires, `financial_ratios` retourne un dictionnaire imbrique
    `ratio1`/`ratio2` a plat sans lignes repetees) — seul `format=json` est
    servi ici, comme pour `/reports/balance-sheet` et `/reports/cash-flow`
    en JSON (memes rapports non tabulaires par nature)."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    data = financial_ratios(fiscal_year)
    return JsonResponse(data)


@router.get("/accounting/reports/analytical-income-statement")
@require_permission("accounting.view_accmove")
def analytical_income_statement_endpoint(
    request, fiscal_year_id: str, analytic_plan_id: str, format: str = "json"
):
    """ACC-ANA — compte de resultat analytique par axe. Cf. docstring de
    `services/reports.py::analytical_income_statement`."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    analytic_plan = get_object_or_404(AccAnalyticPlan, id=analytic_plan_id)
    rows = analytical_income_statement(fiscal_year, analytic_plan)
    data = rows_to_bytes(
        rows,
        ["analytic_account_id", "code", "name", "produits", "charges", "net"],
        format=format,
    )
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


# ---------------------------------------------------------------------------
# A10 — Immobilisations, amortissements, provisions (ACC-ANNEXE1)
# ---------------------------------------------------------------------------


def _serialize_asset(asset: AccAsset) -> dict:
    return {
        "id": str(asset.id),
        "reference": asset.reference,
        "category": asset.category,
        "label": asset.label,
        "account_id": str(asset.account_id),
        "acquisition_date": asset.acquisition_date.isoformat(),
        "acquisition_value_mga": str(asset.acquisition_value_mga),
        "depreciation_method": asset.depreciation_method,
        "useful_life_years": asset.useful_life_years,
        "residual_value_mga": str(asset.residual_value_mga),
        "disposal_date": asset.disposal_date.isoformat() if asset.disposal_date else None,
        "disposal_value_mga": (
            str(asset.disposal_value_mga) if asset.disposal_value_mga is not None else None
        ),
        "state": asset.state,
    }


def _serialize_provision(provision: AccProvision) -> dict:
    return {
        "id": str(provision.id),
        "reference": provision.reference,
        "nature": provision.nature,
        "account_id": str(provision.account_id),
        "fiscal_year_id": str(provision.fiscal_year_id),
        "opening_amount_mga": str(provision.opening_amount_mga),
        "dotation_mga": str(provision.dotation_mga),
        "reprise_mga": str(provision.reprise_mga),
        "closing_amount_mga": str(provision.closing_amount_mga),
    }


@router.get("/accounting/assets")
@require_permission("accounting.view_accasset")
def list_assets_endpoint(request):
    assets = AccAsset.objects.all().order_by("-acquisition_date")
    return {"results": [_serialize_asset(a) for a in assets]}


@router.post("/accounting/assets")
@require_permission("accounting.add_accasset")
def register_asset_endpoint(request, payload: AssetIn):
    account = get_object_or_404(AccAccount, id=payload.account_id)
    try:
        asset = register_asset(
            tenant=account.tenant,
            category=payload.category,
            label=payload.label,
            account=account,
            acquisition_date=payload.acquisition_date,
            acquisition_value_mga=payload.acquisition_value_mga,
            depreciation_method=payload.depreciation_method,
            useful_life_years=payload.useful_life_years,
            residual_value_mga=payload.residual_value_mga,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_asset(asset)


@router.post("/accounting/assets/{asset_id}/dispose")
@require_permission("accounting.change_accasset")
def dispose_asset_endpoint(request, asset_id: str, payload: AssetDisposeIn):
    asset = get_object_or_404(AccAsset, id=asset_id)
    try:
        disposed = dispose_asset(
            asset,
            disposal_date=payload.disposal_date,
            disposal_value_mga=payload.disposal_value_mga,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_asset(disposed)


@router.post("/accounting/assets/{asset_id}/depreciation/compute")
@require_permission("accounting.add_accassetdepreciation")
def compute_asset_depreciation_endpoint(
    request, asset_id: str, payload: AssetDepreciationComputeIn
):
    asset = get_object_or_404(AccAsset, id=asset_id)
    fiscal_year = get_object_or_404(AccFiscalYear, id=payload.fiscal_year_id)
    journal = get_object_or_404(AccJournal, id=payload.journal_id) if payload.journal_id else None
    period = get_object_or_404(AccPeriod, id=payload.period_id) if payload.period_id else None
    dotation_account = (
        get_object_or_404(AccAccount, id=payload.dotation_account_id)
        if payload.dotation_account_id
        else None
    )
    accumulated_account = (
        get_object_or_404(AccAccount, id=payload.accumulated_depreciation_account_id)
        if payload.accumulated_depreciation_account_id
        else None
    )
    try:
        entry = compute_annual_depreciation(
            asset,
            fiscal_year,
            post=payload.post,
            journal=journal,
            period=period,
            dotation_account=dotation_account,
            accumulated_depreciation_account=accumulated_account,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {
        "id": str(entry.id),
        "asset_id": str(entry.asset_id),
        "fiscal_year_id": str(entry.fiscal_year_id),
        "opening_accumulated_mga": str(entry.opening_accumulated_mga),
        "annual_dotation_mga": str(entry.annual_dotation_mga),
        "closing_accumulated_mga": str(entry.closing_accumulated_mga),
        "move_id": str(entry.move_id) if entry.move_id else None,
    }


@router.get("/accounting/provisions")
@require_permission("accounting.view_accprovision")
def list_provisions_endpoint(request):
    provisions = AccProvision.objects.all().order_by("nature")
    return {"results": [_serialize_provision(p) for p in provisions]}


@router.post("/accounting/provisions")
@require_permission("accounting.add_accprovision")
def create_provision_endpoint(request, payload: ProvisionIn):
    account = get_object_or_404(AccAccount, id=payload.account_id)
    fiscal_year = get_object_or_404(AccFiscalYear, id=payload.fiscal_year_id)
    provision = record_provision_movement(
        tenant=account.tenant,
        nature=payload.nature,
        account=account,
        fiscal_year=fiscal_year,
        opening_amount_mga=payload.opening_amount_mga,
        dotation_mga=payload.dotation_mga,
        reprise_mga=payload.reprise_mga,
    )
    return _serialize_provision(provision)


_FIXED_ASSET_ANNEX_FIELDS: dict[str, list[str]] = {
    "actif_immobilise": [
        "categorie",
        "categorie_label",
        "valeur_brute_debut_exercice",
        "acquisitions",
        "cessions_mises_au_rebut",
        "virements_de_poste_a_poste",
        "valeur_brute_fin_exercice",
    ],
    "amortissements": [
        "categorie",
        "categorie_label",
        "cumul_debut_exercice",
        "dotations_de_l_exercice",
        "amortissements_sur_sorties",
        "cumul_fin_exercice",
        "valeur_nette_comptable",
    ],
    "provisions": [
        "nature",
        "montant_debut_exercice",
        "dotations",
        "reprises",
        "montant_fin_exercice",
    ],
    "creances_dettes": ["nature", "moins_d_un_an", "un_a_cinq_ans", "plus_de_cinq_ans", "total"],
}


def _flatten_fixed_asset_annexes(data: dict) -> list[dict]:
    """Aplatit les 4 sous-annexes de `fixed_asset_annexes()` en un unique
    tableau CSV/XLSX (colonne `annexe` en tete pour distinguer les 4
    sous-tableaux aux schemas differents, cf. A12/ACC-EXPORT-FISC1) — le
    format JSON, structure, reste servi directement sans passer par cette
    fonction (meme pattern que `_flatten_balance_sheet`)."""
    rows: list[dict] = []
    for annex_key, fields in _FIXED_ASSET_ANNEX_FIELDS.items():
        for row in data[annex_key]:
            flat = {"annexe": annex_key}
            for field in fields:
                flat[field] = row.get(field)
            rows.append(flat)
    return rows


@router.get("/accounting/reports/fixed-asset-annexes")
@require_permission("accounting.view_accasset")
def fixed_asset_annexes_endpoint(request, fiscal_year_id: str, format: str = "json"):
    """ACC-ANNEXE1 — rapport composite assemblant les 4 annexes fiscales
    (§1.11 du document annexe). Reserve OECFM : cf. docstring de
    `services/reports.py::fixed_asset_annexes`.

    `format=csv|xlsx` (ajoute a l'etape A12, ACC-EXPORT-FISC1) aplatit les 4
    sous-tableaux en un unique fichier tabulaire via `_flatten_fixed_asset_annexes`
    (colonne `annexe` en tete) — `format=json` (par defaut) reste la
    structure composite native, plus lisible pour un ecran."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    data = fixed_asset_annexes(fiscal_year)
    if format == "json":
        return JsonResponse(data)
    rows = _flatten_fixed_asset_annexes(data)
    fields = ["annexe"] + sorted(
        {f for fields in _FIXED_ASSET_ANNEX_FIELDS.values() for f in fields}, key=lambda f: f
    )
    # Ordre stable et complet des colonnes malgre des schemas differents par
    # sous-annexe (cellules vides pour les colonnes non applicables a une
    # ligne donnee) — simple, robuste, pas de perte d'information.
    payload = rows_to_bytes(rows, fields, format=format)
    return HttpResponse(payload, content_type=_REPORT_CONTENT_TYPES[format])


# ---------------------------------------------------------------------------
# A11 — Declarations fiscales specifiques (ACC-DCOM1, ACC-IRCM, ACC-FONCIER)
# ---------------------------------------------------------------------------


def _serialize_dcom_declaration(declaration: AccDcomDeclaration) -> dict:
    return {
        "id": str(declaration.id),
        "reference": declaration.reference,
        "fiscal_year_id": str(declaration.fiscal_year_id),
        "date_generated": declaration.date_generated.isoformat(),
        "total_amount_mga": str(declaration.total_amount_mga),
    }


@router.post("/accounting/reports/dcom/generate")
@require_permission("accounting.add_accdcomdeclaration")
def generate_dcom_endpoint(request, payload: DcomGenerateIn):
    """ACC-DCOM1 — genere (ou regenere) la declaration DCOM de l'exercice.
    Reserve OECFM/DGI sur la classification : cf. docstring de
    `services/dcom.py`."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=payload.fiscal_year_id)
    declaration = generate_dcom_declaration(fiscal_year)
    return _serialize_dcom_declaration(declaration)


@router.get("/accounting/reports/dcom/{declaration_id}")
@require_permission("accounting.view_accdcomdeclaration")
def dcom_report_endpoint(request, declaration_id: str, format: str = "json"):
    """ACC-DCOM1 — rapport plat (canevas DGI approche), noms de tiers
    resolus via `apps.partners.services.public.get_partner_display_name`."""
    declaration = get_object_or_404(AccDcomDeclaration, id=declaration_id)
    rows = dcom_report(declaration)
    data = rows_to_bytes(
        rows, ["partner_id", "partner_name", "classification", "amount_mga"], format=format
    )
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


def _serialize_ircm_declaration(declaration: AccIrcmDeclaration) -> dict:
    return {
        "id": str(declaration.id),
        "reference": declaration.reference,
        "fiscal_year_id": str(declaration.fiscal_year_id),
        "taxable_base_mga": str(declaration.taxable_base_mga),
        "rate_pct": str(declaration.rate_pct),
        "amount_due_mga": str(declaration.amount_due_mga),
        "state": declaration.state,
    }


@router.post("/accounting/reports/ircm/generate")
@require_permission("accounting.add_accircmdeclaration")
def generate_ircm_endpoint(request, payload: IrcmGenerateIn):
    """ACC-IRCM — genere (ou regenere) la declaration IRCM annuelle de
    l'exercice. Reserve au regime reel (ValidationError sinon) — cf.
    docstring de `services/ircm.py`."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=payload.fiscal_year_id)
    try:
        declaration = generate_ircm_declaration(fiscal_year, rate_pct=payload.rate_pct)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_ircm_declaration(declaration)


def _serialize_local_tax(local_tax: AccLocalTax) -> dict:
    return {
        "id": str(local_tax.id),
        "reference": local_tax.reference,
        "tax_type": local_tax.tax_type,
        "property_label": local_tax.property_label,
        "assessed_value_mga": str(local_tax.assessed_value_mga),
        "rate_pct": str(local_tax.rate_pct),
        "fiscal_year_id": str(local_tax.fiscal_year_id),
        "amount_due_mga": str(local_tax.amount_due_mga),
        "state": local_tax.state,
    }


@router.get("/accounting/local-taxes")
@require_permission("accounting.view_acclocaltax")
def list_local_taxes_endpoint(request):
    """ACC-FONCIER — liste des impots locaux fonciers (IFT/IFPB) enregistres
    manuellement (priorite basse, cf. docstring de `services/local_tax.py`)."""
    return {
        "results": [
            _serialize_local_tax(t)
            for t in AccLocalTax.objects.all().order_by("-fiscal_year__date_end")
        ]
    }


@router.post("/accounting/local-taxes")
@require_permission("accounting.add_acclocaltax")
def create_local_tax_endpoint(request, payload: LocalTaxIn):
    fiscal_year = get_object_or_404(AccFiscalYear, id=payload.fiscal_year_id)
    local_tax = record_local_tax(
        tenant=fiscal_year.tenant,
        tax_type=payload.tax_type,
        property_label=payload.property_label,
        assessed_value_mga=payload.assessed_value_mga,
        rate_pct=payload.rate_pct,
        fiscal_year=fiscal_year,
    )
    return _serialize_local_tax(local_tax)


# ---------------------------------------------------------------------------
# A12 — Liasses fiscales et export reglementaire (ACC-IS, ACC-IR,
# ACC-EXPORT-FISC1)
# ---------------------------------------------------------------------------


@router.get("/accounting/reports/liasse-is")
@require_permission("accounting.view_accaccount")
def liasse_is_endpoint(request, fiscal_year_id: str):
    """ACC-IS — liasse fiscale composite PDF (regime Impot Synthetique,
    seuil haut) : bilan + CR nature + CR fonction + flux de tresorerie.
    Reserve OECFM/DGI sur l'ordonnancement des sections : cf. docstring de
    `services/tax_returns.py`. 400 si le tenant n'est pas au regime
    synthetique (cf. `generate_liasse_is`)."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    try:
        pdf_bytes = generate_liasse_is(fiscal_year)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="liasse-is-{fiscal_year.code}.pdf"'
    return response


@router.get("/accounting/reports/liasse-ir")
@require_permission("accounting.view_accaccount")
def liasse_ir_endpoint(request, fiscal_year_id: str):
    """ACC-IR — liasse fiscale composite PDF (regime reel) : les 5 etats
    financiers de base plus les 4 annexes fiscales. Reserve OECFM/DGI sur
    l'ordonnancement des sections : cf. docstring de
    `services/tax_returns.py`. 400 si le tenant n'est pas au regime reel
    (cf. `generate_liasse_ir`)."""
    fiscal_year = get_object_or_404(AccFiscalYear, id=fiscal_year_id)
    try:
        pdf_bytes = generate_liasse_ir(fiscal_year)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="liasse-ir-{fiscal_year.code}.pdf"'
    return response


@router.get("/accounting/reports/export-canevas-notes")
@require_permission("accounting.view_accaccount")
def export_canevas_notes_endpoint(request):
    """ACC-EXPORT-FISC1 — registre documentaire associant a chaque rapport
    fiscal deja construit (A8-A12) une note sur la plateforme/le canevas DGI
    (eHetra/DConline) que son export CSV/XLSX vise a approcher. PAS une
    specification d'export byte-pres supplementaire : chaque rapport
    concerne est deja exportable via son propre endpoint
    `format=csv|xlsx` (`rows_to_bytes`, cf. `services/reports.py`) — ce
    registre documente seulement, avec la reserve OECFM/DGI explicite,
    l'intention derriere chaque export. Cf. docstring de
    `services/fiscal_export.py`."""
    return JsonResponse({"results": export_canevas_notes()})
