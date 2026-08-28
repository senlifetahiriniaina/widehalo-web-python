from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.files import UploadedFile

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccAnalyticPlan,
    AccAsset,
    AccBankStatementLine,
    AccBudget,
    AccBudgetLine,
    AccDcomDeclaration,
    AccDunningAction,
    AccDunningLevel,
    AccFiscalYear,
    AccImportRow,
    AccIrcmDeclaration,
    AccJournal,
    AccLandedCostBatch,
    AccLandedCostComponent,
    AccLandedCostLine,
    AccLocalTax,
    AccMobileMoneyStatementLine,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccPeriod,
    AccProvision,
    AccReconcileRule,
    AccTaxCalendar,
)
from apps.accounting.services.assets import (
    compute_annual_depreciation,
    dispose_asset,
    record_provision_movement,
    register_asset,
)
from apps.accounting.services.bank_reconciliation import (
    confirm_reconciliation,
    import_bank_statement,
    manual_match,
    suggest_matches,
    unmatched_or_suggested_lines,
)
from apps.accounting.services.budgets import (
    add_budget_line,
    approve_budget,
    budget_variance_report,
    create_budget,
)
from apps.accounting.services.cash_journal_import import (
    import_cash_journal_xlsx,
    resolve_import_row,
)
from apps.accounting.services.chart_of_accounts_import import import_chart_of_accounts_xlsx
from apps.accounting.services.dcom import generate_dcom_declaration
from apps.accounting.services.dunning import (
    overdue_receivables,
    record_dunning_action,
    seed_default_dunning_levels,
)
from apps.accounting.services.fiscal_export import export_canevas_notes
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    create_invoice,
    validate_invoice,
)
from apps.accounting.services.ircm import generate_ircm_declaration
from apps.accounting.services.landed_costs import (
    add_cost_component,
    add_landed_cost_line,
    create_landed_cost_batch,
    finalize_batch,
    landed_cost_report,
)
from apps.accounting.services.local_tax import record_local_tax
from apps.accounting.services.mobile_money import (
    import_mobile_money_statement,
    reconcile_mobile_money_line,
    unmatched_mobile_money_lines,
)
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
    treasury_forecast,
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


class BudgetIn(Schema):
    fiscal_year_id: str
    name: str


class BudgetLineIn(Schema):
    account_id: str
    budgeted_amount_mga: Decimal
    period_id: str | None = None
    analytic_account_id: str | None = None


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


class DunningLevelIn(Schema):
    level: int
    label: str
    days_overdue_threshold: int
    message_template: str = ""


class DunningActionIn(Schema):
    move_line_id: str
    level_id: str
    date_sent: dt.date | None = None
    notes: str = ""


class MobileMoneyReconcileIn(Schema):
    payment_id: str


class ImportRowResolveIn(Schema):
    account_id: str | None = None
    date: dt.date | None = None
    discard: bool = False


class ReconcileRuleIn(Schema):
    name: str
    bank_account_id: str | None = None
    match_on_amount: bool = True
    amount_tolerance_mga: Decimal = Decimal(0)
    match_on_reference: bool = False
    match_on_partner: bool = False
    priority: int = 0
    is_active: bool = True


class ConfirmReconciliationIn(Schema):
    move_line_id: str | None = None


class ManualMatchIn(Schema):
    move_line_id: str


class LandedCostBatchIn(Schema):
    label: str
    date: dt.date
    allocation_method: str
    currency: str = "MGA"


class LandedCostLineIn(Schema):
    description: str
    qty: Decimal
    purchase_value_mga: Decimal
    variant_id: str | None = None
    weight_kg: Decimal | None = None


class LandedCostComponentIn(Schema):
    label: str
    amount_mga: Decimal
    account_id: str | None = None


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


# ---------------------------------------------------------------------------
# A14 — Budgets et analyse d'ecart
# ---------------------------------------------------------------------------


def _serialize_budget(budget: AccBudget) -> dict:
    return {
        "id": str(budget.id),
        "reference": budget.reference,
        "fiscal_year_id": str(budget.fiscal_year_id),
        "name": budget.name,
        "state": budget.state,
    }


def _serialize_budget_line(line: AccBudgetLine) -> dict:
    return {
        "id": str(line.id),
        "budget_id": str(line.budget_id),
        "account_id": str(line.account_id),
        "period_id": str(line.period_id) if line.period_id else None,
        "analytic_account_id": str(line.analytic_account_id) if line.analytic_account_id else None,
        "budgeted_amount_mga": str(line.budgeted_amount_mga),
    }


@router.get("/accounting/budgets")
@require_permission("accounting.view_accbudget")
def list_budgets_endpoint(request):
    budgets = AccBudget.objects.all().order_by("-fiscal_year__date_start")
    return {"results": [_serialize_budget(b) for b in budgets]}


@router.post("/accounting/budgets")
@require_permission("accounting.add_accbudget")
def create_budget_endpoint(request, payload: BudgetIn):
    fiscal_year = get_object_or_404(AccFiscalYear, id=payload.fiscal_year_id)
    budget = create_budget(tenant=fiscal_year.tenant, fiscal_year=fiscal_year, name=payload.name)
    return _serialize_budget(budget)


@router.post("/accounting/budgets/{budget_id}/lines")
@require_permission("accounting.change_accbudget")
def add_budget_line_endpoint(request, budget_id: str, payload: BudgetLineIn):
    budget = get_object_or_404(AccBudget, id=budget_id)
    account = get_object_or_404(AccAccount, id=payload.account_id)
    period = get_object_or_404(AccPeriod, id=payload.period_id) if payload.period_id else None
    analytic_account = (
        get_object_or_404(AccAnalyticAccount, id=payload.analytic_account_id)
        if payload.analytic_account_id
        else None
    )
    try:
        line = add_budget_line(
            budget,
            account=account,
            budgeted_amount_mga=payload.budgeted_amount_mga,
            period=period,
            analytic_account=analytic_account,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_budget_line(line)


@router.post("/accounting/budgets/{budget_id}/approve")
@require_permission("accounting.change_accbudget")
def approve_budget_endpoint(request, budget_id: str):
    budget = get_object_or_404(AccBudget, id=budget_id)
    try:
        approved = approve_budget(budget)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_budget(approved)


@router.get("/accounting/budgets/{budget_id}/variance-report")
@require_permission("accounting.view_accbudget")
def budget_variance_report_endpoint(request, budget_id: str, format: str = "json"):
    """A14 — rapport d'ecart reel vs budget. `period=None` sur une ligne
    signifie "etale sur l'exercice" (comparaison au reel cumule de tout
    `budget.fiscal_year`) — cf. docstring de `AccBudgetLine`/
    `services/budgets.py::budget_variance_report`."""
    budget = get_object_or_404(AccBudget, id=budget_id)
    rows = budget_variance_report(budget)
    data = rows_to_bytes(
        rows,
        [
            "account_code",
            "account_name",
            "period_label",
            "analytic_account_label",
            "budgeted_amount_mga",
            "actual_amount_mga",
            "variance_mga",
            "variance_pct",
        ],
        format=format,
    )
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


# ---------------------------------------------------------------------------
# A15 — Tresorerie previsionnelle (ACC-TRESO), relances client (ACC-REL,
# RG-ACC-11), reconciliation mobile money simple
# ---------------------------------------------------------------------------


@router.get("/accounting/reports/treasury-forecast")
@require_permission("accounting.view_accaccount")
def treasury_forecast_endpoint(request, horizon_days: int = 90, as_of_date: dt.date | None = None):
    """ACC-TRESO — previsionnel de tresorerie glissant, paniers hebdomadaires
    et detection de creux (ACC-TR1). Reserve/choix de granularite : cf.
    docstring de `services/reports.py::treasury_forecast`."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    data = treasury_forecast(tenant, as_of_date=as_of_date, horizon_days=horizon_days)
    return JsonResponse(data)


def _serialize_dunning_level(level: AccDunningLevel) -> dict:
    return {
        "id": str(level.id),
        "level": level.level,
        "label": level.label,
        "days_overdue_threshold": level.days_overdue_threshold,
        "message_template": level.message_template,
    }


@router.get("/accounting/dunning-levels")
@require_permission("accounting.view_accdunninglevel")
def list_dunning_levels_endpoint(request):
    """ACC-REL — niveaux de relance configures pour le tenant courant. Cf.
    `POST` sur le meme chemin pour amorcer les 3 niveaux par defaut."""
    levels = AccDunningLevel.objects.all().order_by("level")
    return {"results": [_serialize_dunning_level(entry) for entry in levels]}


@router.post("/accounting/dunning-levels")
@require_permission("accounting.add_accdunninglevel")
def create_dunning_level_endpoint(request, payload: DunningLevelIn):
    """ACC-REL — cree/ajuste (par `level`) un niveau de relance precis pour
    ce tenant. Cf. `POST .../dunning-levels/seed` pour amorcer directement
    les 3 niveaux par defaut sans en saisir le detail."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    level, _created = AccDunningLevel.objects.update_or_create(
        tenant=tenant,
        level=payload.level,
        defaults={
            "label": payload.label,
            "days_overdue_threshold": payload.days_overdue_threshold,
            "message_template": payload.message_template,
        },
    )
    return _serialize_dunning_level(level)


@router.post("/accounting/dunning-levels/seed")
@require_permission("accounting.add_accdunninglevel")
def seed_dunning_levels_endpoint(request):
    """ACC-REL — amorce les 3 niveaux par defaut pour ce tenant (idempotent,
    cf. `seed_default_dunning_levels` — n'ecrase jamais un niveau deja
    personnalise par le tenant)."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    levels = seed_default_dunning_levels(tenant)
    return {"results": [_serialize_dunning_level(entry) for entry in levels]}


@router.get("/accounting/reports/overdue-receivables")
@require_permission("accounting.view_accmove")
def overdue_receivables_endpoint(request, as_of_date: dt.date | None = None):
    """ACC-REL — creances clients en retard, niveau de relance applicable.
    Cf. docstring de `services/dunning.py::overdue_receivables`."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    rows = overdue_receivables(tenant, as_of_date=as_of_date)
    return {"results": rows}


def _serialize_dunning_action(action: AccDunningAction) -> dict:
    return {
        "id": str(action.id),
        "reference": action.reference,
        "move_line_id": str(action.move_line_id),
        "level_id": str(action.level_id),
        "date_sent": action.date_sent.isoformat(),
        "notes": action.notes,
    }


@router.post("/accounting/dunning-actions")
@require_permission("accounting.add_accdunningaction")
def create_dunning_action_endpoint(request, payload: DunningActionIn):
    """ACC-REL — enregistre qu'une relance a ete envoyee (V1 : simple trace,
    aucun envoi automatise — cf. docstring de
    `services/dunning.py::record_dunning_action`)."""
    move_line = get_object_or_404(AccMoveLine, id=payload.move_line_id)
    level = get_object_or_404(AccDunningLevel, id=payload.level_id)
    action = record_dunning_action(
        move_line, level, date_sent=payload.date_sent, notes=payload.notes
    )
    return _serialize_dunning_action(action)


def _serialize_mobile_money_line(line: AccMobileMoneyStatementLine) -> dict:
    return {
        "id": str(line.id),
        "import_batch_id": str(line.import_batch_id),
        "statement_date": line.statement_date.isoformat(),
        "reference_external": line.reference_external,
        "amount_mga": str(line.amount_mga),
        "direction": line.direction,
        "matched_payment_id": str(line.matched_payment_id) if line.matched_payment_id else None,
        "state": line.state,
    }


@router.post("/accounting/mobile-money/import")
@require_permission("accounting.add_accmobilemoneystatementline")
def import_mobile_money_endpoint(
    request,
    statement: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
):
    """Reconciliation mobile money simple (PAS le mecanisme generique d'A16,
    cf. docstring de `services/mobile_money.py`) : import multipart d'un CSV
    de relevé (colonnes `date`/`reference`/`amount`/`direction`, format
    placeholder documente sur le service). Meme idiome multipart que
    `apps.chat.api.create_message` (`ninja.File`/`UploadedFile`), seul
    exemple existant d'upload de fichier via django-ninja dans ce depot."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        lines = import_mobile_money_statement(tenant, statement.read())
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"results": [_serialize_mobile_money_line(line) for line in lines]}


@router.post("/accounting/mobile-money/{line_id}/reconcile")
@require_permission("accounting.change_accmobilemoneystatementline")
def reconcile_mobile_money_endpoint(request, line_id: str, payload: MobileMoneyReconcileIn):
    """Rapprochement MANUEL/ASSISTE uniquement en V1 (pas de correspondance
    floue automatique) — cf. docstring de
    `services/mobile_money.py::reconcile_mobile_money_line`."""
    statement_line = get_object_or_404(AccMobileMoneyStatementLine, id=line_id)
    payment = get_object_or_404(AccPayment, id=payload.payment_id)
    try:
        reconciled = reconcile_mobile_money_line(statement_line, payment)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_mobile_money_line(reconciled)


@router.get("/accounting/mobile-money/unmatched")
@require_permission("accounting.view_accmobilemoneystatementline")
def unmatched_mobile_money_endpoint(request):
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    lines = unmatched_mobile_money_lines(tenant)
    return {"results": [_serialize_mobile_money_line(line) for line in lines]}


# ---------------------------------------------------------------------------
# A16 — Rapprochement bancaire assiste par regles (acc_reconcile_rule)
# ---------------------------------------------------------------------------


def _serialize_reconcile_rule(rule: AccReconcileRule) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "bank_account_id": str(rule.bank_account_id) if rule.bank_account_id else None,
        "match_on_amount": rule.match_on_amount,
        "amount_tolerance_mga": str(rule.amount_tolerance_mga),
        "match_on_reference": rule.match_on_reference,
        "match_on_partner": rule.match_on_partner,
        "priority": rule.priority,
        "is_active": rule.is_active,
    }


def _serialize_bank_statement_line(line: AccBankStatementLine) -> dict:
    return {
        "id": str(line.id),
        "bank_account_id": str(line.bank_account_id),
        "import_batch_id": str(line.import_batch_id),
        "statement_date": line.statement_date.isoformat(),
        "reference_external": line.reference_external,
        "label": line.label,
        "amount_mga": str(line.amount_mga),
        "direction": line.direction,
        "partner_id": str(line.partner_id) if line.partner_id else None,
        "matched_move_line_id": (
            str(line.matched_move_line_id) if line.matched_move_line_id else None
        ),
        "state": line.state,
    }


@router.get("/accounting/reconcile-rules")
@require_permission("accounting.view_accreconcilerule")
def list_reconcile_rules_endpoint(request):
    """A16 — regles actives et inactives du tenant courant, dans l'ordre
    d'evaluation (`-priority`, cf. `AccReconcileRule.Meta.ordering`)."""
    rules = AccReconcileRule.objects.all()
    return {"results": [_serialize_reconcile_rule(rule) for rule in rules]}


@router.post("/accounting/reconcile-rules")
@require_permission("accounting.add_accreconcilerule")
def create_reconcile_rule_endpoint(request, payload: ReconcileRuleIn):
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    bank_account = (
        get_object_or_404(AccAccount, id=payload.bank_account_id)
        if payload.bank_account_id
        else None
    )
    rule = AccReconcileRule.objects.create(
        tenant=tenant,
        name=payload.name,
        bank_account=bank_account,
        match_on_amount=payload.match_on_amount,
        amount_tolerance_mga=payload.amount_tolerance_mga,
        match_on_reference=payload.match_on_reference,
        match_on_partner=payload.match_on_partner,
        priority=payload.priority,
        is_active=payload.is_active,
    )
    return _serialize_reconcile_rule(rule)


@router.post("/accounting/bank-reconciliation/import")
@require_permission("accounting.add_accbankstatementline")
def import_bank_statement_endpoint(
    request,
    bank_account_id: str,
    statement: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
):
    """Import multipart d'un relevé bancaire CSV (colonnes
    `date`/`reference`/`label`/`amount`/`direction`, format placeholder
    documente sur `services/bank_reconciliation.py`). Meme idiome multipart
    que `import_mobile_money_endpoint`/`apps.chat.api.create_message`."""
    bank_account = get_object_or_404(AccAccount, id=bank_account_id)
    try:
        lines = import_bank_statement(bank_account, statement.read())
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"results": [_serialize_bank_statement_line(line) for line in lines]}


@router.post("/accounting/bank-reconciliation/{bank_account_id}/suggest-matches")
@require_permission("accounting.change_accbankstatementline")
def suggest_matches_endpoint(request, bank_account_id: str):
    """A16 — evalue les `AccReconcileRule` actives sur ce compte (portee ou
    globales) sur toutes les lignes `unmatched` — cf. docstring de
    `services/bank_reconciliation.py::suggest_matches`. Rapprochement
    ASSISTE uniquement : les lignes retournees passent en
    `rule_suggested`, jamais directement `matched`."""
    bank_account = get_object_or_404(AccAccount, id=bank_account_id)
    lines = suggest_matches(bank_account)
    return {"results": [_serialize_bank_statement_line(line) for line in lines]}


@router.post("/accounting/bank-reconciliation/{line_id}/confirm")
@require_permission("accounting.change_accbankstatementline")
def confirm_reconciliation_endpoint(request, line_id: str, payload: ConfirmReconciliationIn):
    """Confirmation HUMAINE d'une suggestion de regle (`state="rule_suggested"`
    requis), ou rapprochement manuel direct si `move_line_id` est fourni —
    cf. docstring de `services/bank_reconciliation.py::confirm_reconciliation`."""
    statement_line = get_object_or_404(AccBankStatementLine, id=line_id)
    move_line = (
        get_object_or_404(AccMoveLine, id=payload.move_line_id) if payload.move_line_id else None
    )
    try:
        confirmed = confirm_reconciliation(statement_line, move_line=move_line)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_bank_statement_line(confirmed)


@router.post("/accounting/bank-reconciliation/{line_id}/manual-match")
@require_permission("accounting.change_accbankstatementline")
def manual_match_endpoint(request, line_id: str, payload: ManualMatchIn):
    """Rapprochement manuel direct sans passer par aucune regle — cf.
    docstring de `services/bank_reconciliation.py::manual_match`."""
    statement_line = get_object_or_404(AccBankStatementLine, id=line_id)
    move_line = get_object_or_404(AccMoveLine, id=payload.move_line_id)
    matched = manual_match(statement_line, move_line)
    return _serialize_bank_statement_line(matched)


@router.get("/accounting/bank-reconciliation/{bank_account_id}/unmatched")
@require_permission("accounting.view_accbankstatementline")
def unmatched_bank_reconciliation_endpoint(request, bank_account_id: str):
    """Liste de travail (`unmatched` + `rule_suggested`) pour ce compte
    bancaire — cf. docstring de
    `services/bank_reconciliation.py::unmatched_or_suggested_lines`."""
    bank_account = get_object_or_404(AccAccount, id=bank_account_id)
    lines = unmatched_or_suggested_lines(bank_account)
    return {"results": [_serialize_bank_statement_line(line) for line in lines]}


# ---------------------------------------------------------------------------
# A17 — Couts d'importation (landed costs), ACC-IMP : calculateur autonome,
# sans integration reelle a une valorisation de stock (`stocks` n'existe pas
# encore) — cf. docstring de `services/landed_costs.py`.
# ---------------------------------------------------------------------------


def _serialize_landed_cost_batch(batch: AccLandedCostBatch) -> dict:
    return {
        "id": str(batch.id),
        "reference": batch.reference,
        "label": batch.label,
        "date": batch.date.isoformat(),
        "currency": batch.currency,
        "total_purchase_value_mga": str(batch.total_purchase_value_mga),
        "allocation_method": batch.allocation_method,
        "state": batch.state,
    }


def _serialize_landed_cost_line(line: AccLandedCostLine) -> dict:
    return {
        "id": str(line.id),
        "batch_id": str(line.batch_id),
        "description": line.description,
        "variant_id": str(line.variant_id) if line.variant_id else None,
        "qty": str(line.qty),
        "weight_kg": str(line.weight_kg) if line.weight_kg is not None else None,
        "purchase_value_mga": str(line.purchase_value_mga),
    }


def _serialize_landed_cost_component(component: AccLandedCostComponent) -> dict:
    return {
        "id": str(component.id),
        "batch_id": str(component.batch_id),
        "label": component.label,
        "amount_mga": str(component.amount_mga),
        "account_id": str(component.account_id) if component.account_id else None,
    }


@router.get("/accounting/landed-cost-batches")
@require_permission("accounting.view_acclandedcostbatch")
def list_landed_cost_batches_endpoint(request):
    batches = AccLandedCostBatch.objects.all().order_by("-date")
    return {"results": [_serialize_landed_cost_batch(b) for b in batches]}


@router.post("/accounting/landed-cost-batches")
@require_permission("accounting.add_acclandedcostbatch")
def create_landed_cost_batch_endpoint(request, payload: LandedCostBatchIn):
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    batch = create_landed_cost_batch(
        tenant=tenant,
        label=payload.label,
        date=payload.date,
        allocation_method=payload.allocation_method,
        currency=payload.currency,
    )
    return _serialize_landed_cost_batch(batch)


@router.post("/accounting/landed-cost-batches/{batch_id}/lines")
@require_permission("accounting.change_acclandedcostbatch")
def add_landed_cost_line_endpoint(request, batch_id: str, payload: LandedCostLineIn):
    batch = get_object_or_404(AccLandedCostBatch, id=batch_id)
    try:
        line = add_landed_cost_line(
            batch,
            description=payload.description,
            qty=payload.qty,
            purchase_value_mga=payload.purchase_value_mga,
            variant_id=uuid.UUID(payload.variant_id) if payload.variant_id else None,
            weight_kg=payload.weight_kg,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_landed_cost_line(line)


@router.post("/accounting/landed-cost-batches/{batch_id}/cost-components")
@require_permission("accounting.change_acclandedcostbatch")
def add_landed_cost_component_endpoint(request, batch_id: str, payload: LandedCostComponentIn):
    batch = get_object_or_404(AccLandedCostBatch, id=batch_id)
    account = get_object_or_404(AccAccount, id=payload.account_id) if payload.account_id else None
    try:
        component = add_cost_component(
            batch, label=payload.label, amount_mga=payload.amount_mga, account=account
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_landed_cost_component(component)


@router.post("/accounting/landed-cost-batches/{batch_id}/finalize")
@require_permission("accounting.change_acclandedcostbatch")
def finalize_landed_cost_batch_endpoint(request, batch_id: str):
    batch = get_object_or_404(AccLandedCostBatch, id=batch_id)
    try:
        finalized = finalize_batch(batch)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_landed_cost_batch(finalized)


@router.get("/accounting/landed-cost-batches/{batch_id}/report")
@require_permission("accounting.view_acclandedcostbatch")
def landed_cost_report_endpoint(request, batch_id: str, format: str = "json"):
    """ACC-IMP — rapport de repartition des couts d'importation. Cf.
    docstring de `services/landed_costs.py::landed_cost_report`."""
    batch = get_object_or_404(AccLandedCostBatch, id=batch_id)
    try:
        rows = landed_cost_report(batch)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    data = rows_to_bytes(
        rows,
        [
            "description",
            "variant_id",
            "qty",
            "purchase_value_mga",
            "allocation_key_pct",
            "allocated_cost_mga",
            "landed_total_mga",
            "landed_unit_cost_mga",
        ],
        format=format,
    )
    return HttpResponse(data, content_type=_REPORT_CONTENT_TYPES[format])


# ---------------------------------------------------------------------------
# Import comptable/caisse depuis Excel (cf. docs/IMPORT_FORMATS.md)
# ---------------------------------------------------------------------------


def _serialize_import_row(row: AccImportRow) -> dict:
    return {
        "id": str(row.id),
        "row_number": row.row_number,
        "status": row.status,
        "anomaly_codes": row.anomaly_codes,
        "resolved_account_id": str(row.resolved_account_id) if row.resolved_account_id else None,
        "move_id": str(row.move_id) if row.move_id else None,
    }


@router.post("/accounting/imports/chart-of-accounts")
@require_permission("accounting.add_accaccount")
def import_chart_of_accounts_endpoint(
    request,
    file: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
):
    """Import xlsx du plan comptable — cf. docstring de
    `services/chart_of_accounts_import.py`/`docs/IMPORT_FORMATS.md`. Meme
    idiome multipart que `import_mobile_money_endpoint`/
    `import_bank_statement_endpoint`."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        summary = import_chart_of_accounts_xlsx(tenant, file.read(), filename=file.name)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return {
        "is_valid": summary.is_valid,
        "total_rows": summary.total_rows,
        "created_count": summary.created_count,
        "skipped_existing_count": summary.skipped_existing_count,
        "category_mappings_count": summary.category_mappings_count,
        "row_errors": [
            {"row_index": row_error.row_index, "errors": row_error.errors}
            for row_error in summary.row_errors
        ],
    }


@router.post("/accounting/imports/cash-journal")
@require_permission("accounting.add_accimportbatch")
def import_cash_journal_endpoint(
    request,
    file: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
):
    """Import xlsx du journal de caisse — cf. docstring de
    `services/cash_journal_import.py`/`docs/IMPORT_FORMATS.md`. La caisse
    cible est resolue PAR LIGNE depuis la colonne CAISSE du fichier (pas un
    parametre unique de lot — les donnees reelles observees melangent
    plusieurs caisses physiques dans un meme classeur)."""
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        summary = import_cash_journal_xlsx(tenant, file.read(), filename=file.name)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    anomaly_rows = summary.batch.rows.filter(status=AccImportRow.STATUS_ANOMALY)
    return {
        "batch_id": str(summary.batch.id),
        "total_rows": summary.total_rows,
        "ok_count": summary.ok_count,
        "anomaly_count": summary.anomaly_count,
        "batch_warnings": summary.batch_warnings,
        "anomaly_rows": [_serialize_import_row(row) for row in anomaly_rows],
    }


@router.post("/accounting/imports/cash-journal/rows/{row_id}/resolve")
@require_permission("accounting.change_accimportrow")
def resolve_cash_journal_import_row_endpoint(request, row_id: str, payload: ImportRowResolveIn):
    """Applique `resolve_import_row` — corrige (compte/date) ou ecarte
    volontairement une ligne en anomalie (cf. `AccImportRow.STATUS_ANOMALY`).
    Jamais de resolution devinee : le compte/la date viennent toujours d'une
    action humaine explicite."""
    row = get_object_or_404(AccImportRow, id=row_id)
    account = get_object_or_404(AccAccount, id=payload.account_id) if payload.account_id else None
    resolved = resolve_import_row(row, account=account, date=payload.date, discard=payload.discard)
    return _serialize_import_row(resolved)
