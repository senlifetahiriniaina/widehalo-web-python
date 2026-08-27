from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccPayment, AccPeriod
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    create_invoice,
    validate_invoice,
)
from apps.accounting.services.moves import post_move, reverse_move
from apps.accounting.services.payments import register_payment
from apps.accounting.services.reports import (
    general_ledger,
    invoice_pdf,
    journal_report,
    rows_to_bytes,
    trial_balance,
)
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
