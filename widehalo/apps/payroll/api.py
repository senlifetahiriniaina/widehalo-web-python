"""API django-ninja du module `payroll` (§5.10.9). RG-PAY-9 : un
`collaborateur` ne voit que ses propres bulletins (scope N3 "own",
resolu via `presence.services.public.get_employee_id_for_user`) ; RH/
direction/admin voient tout ; les roles "manager" (`resp_production`/
`chef_atelier`/`resp_commercial`) voient la liste mais jamais les montants
(`filter_fields_for_role`, N4)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

import apps.presence.services.public as presence_public
from apps.core.services.audit import log_pii_access
from apps.core.services.permissions import (
    SENSITIVE_FIELDS,
    filter_fields_for_role,
    require_permission,
    user_role_codes,
)
from apps.payroll.models import (
    PayAdvance,
    PayContract,
    PayContractType,
    PayDeclaration,
    PayPayslip,
    PaySalaryStructure,
)
from apps.payroll.services.advances import request_advance
from apps.payroll.services.batches import control_batch, create_batch, validate_and_post_batch
from apps.payroll.services.contracts import create_contract
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.services.pdf import payslip_pdf
from apps.payroll.services.periods import close_period, compute_period, mark_period_paid
from apps.payroll.services.periods import create_period as create_period_service

router = Router(tags=["payroll"])

_STAFF_ROLES = {"rh", "admin", "direction"}


def _error_response(exc: Exception) -> JsonResponse:
    message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return JsonResponse({"detail": message}, status=400)


def _tenant(request: Any) -> Any:
    from apps.core.models.tenant import Tenant

    tenant_id: str = request.headers.get("X-Tenant-Id")
    return Tenant.objects.get(id=tenant_id)


def _own_employee_id(request: Any) -> uuid.UUID | None:
    return presence_public.get_employee_id_for_user(_tenant(request), request.auth)


def _serialize_payslip(payslip: PayPayslip, role_codes: set[str], actor: Any) -> dict[str, Any]:
    """Phase 3 §5 (audit, decision P5) : point reel de « revelation » d'un
    montant masque par N4 (`SENSITIVE_FIELDS`) — le masquage lui-meme reste
    binaire (champ present ou absent, `filter_fields_for_role`), mais
    chaque fois qu'un champ sensible EST effectivement inclus pour ce
    role (montant vraiment revele a l'acteur courant), l'acces est
    journalise via `log_pii_access` (existait deja, jamais appele avant ce
    correctif)."""
    data = {
        "id": str(payslip.id),
        "reference": payslip.reference,
        "employee_id": str(payslip.employee_id),
        "period_id": str(payslip.period_id),
        "state": payslip.state,
        "worked_days": payslip.worked_days,
        "gross": payslip.gross,
        "taxable_base": payslip.taxable_base,
        "irsa": payslip.irsa,
        "social_employee": payslip.social_employee,
        "social_employer": payslip.social_employer,
        "net_to_pay": payslip.net_to_pay,
    }
    filtered = filter_fields_for_role("payroll.PayPayslip", role_codes, data)
    sensitive_fields = SENSITIVE_FIELDS.get("payroll.PayPayslip", {}).keys()
    revealed_amount_fields = sorted(sensitive_fields & filtered.keys())
    if revealed_amount_fields:
        log_pii_access(actor, payslip, revealed_amount_fields)
    return filtered


class ContractTypeIn(Schema):
    code: str
    name: str
    category: str
    default_notice_days: int = 0


class ContractIn(Schema):
    employee_id: uuid.UUID
    type_id: uuid.UUID
    date_start: str
    wage_base: Decimal
    salary_structure_id: uuid.UUID
    wage_type: str = PayContract.WAGE_MONTHLY


class PeriodIn(Schema):
    code: str
    date_from: str
    date_to: str
    payment_date: str


class ComputePeriodIn(Schema):
    employee_ids: list[uuid.UUID]


class AdvanceIn(Schema):
    employee_id: uuid.UUID
    date: str
    amount: Decimal
    reason: str = ""
    repayment_months: int = 1


@router.get("/payroll/contracts")
@require_permission("payroll.view_paycontract")
def list_contracts(request: Any) -> list[dict[str, Any]]:
    contracts = PayContract.objects.filter(is_active=True)
    return [
        {
            "id": str(c.id),
            "reference": c.reference,
            "employee_id": str(c.employee_id),
            "state": c.state,
            "wage_base": c.wage_base,
        }
        for c in contracts
    ]


@router.post("/payroll/contracts")
@require_permission("payroll.add_paycontract")
def create_contract_endpoint(request: Any, payload: ContractIn) -> dict[str, Any] | JsonResponse:
    import datetime as dt

    try:
        contract_type = get_object_or_404(PayContractType, id=payload.type_id)
        structure = get_object_or_404(PaySalaryStructure, id=payload.salary_structure_id)
        contract = create_contract(
            tenant=_tenant(request),
            employee_id=payload.employee_id,
            contract_type=contract_type,
            date_start=dt.date.fromisoformat(payload.date_start),
            wage_base=payload.wage_base,
            salary_structure=structure,
            wage_type=payload.wage_type,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return {"id": str(contract.id), "reference": contract.reference}


@router.get("/payroll/structures")
@require_permission("payroll.view_paysalarystructure")
def list_structures(request: Any) -> list[dict[str, Any]]:
    return [
        {"id": str(s.id), "code": s.code, "name": s.name}
        for s in PaySalaryStructure.objects.filter(is_active=True)
    ]


@router.get("/payroll/periods")
@require_permission("payroll.view_payperiod")
def list_periods(request: Any) -> list[dict[str, Any]]:
    from apps.payroll.models import PayPeriod

    return [
        {"id": str(p.id), "code": p.code, "state": p.state}
        for p in PayPeriod.objects.all().order_by("-date_from")
    ]


@router.post("/payroll/periods")
@require_permission("payroll.add_payperiod")
def create_period_endpoint(request: Any, payload: PeriodIn) -> dict[str, Any]:
    import datetime as dt

    period = create_period_service(
        _tenant(request),
        code=payload.code,
        date_from=dt.date.fromisoformat(payload.date_from),
        date_to=dt.date.fromisoformat(payload.date_to),
        payment_date=dt.date.fromisoformat(payload.payment_date),
    )
    return {"id": str(period.id), "code": period.code}


def _get_period(request: Any, period_id: uuid.UUID) -> Any:
    from apps.payroll.models import PayPeriod

    return get_object_or_404(PayPeriod, id=period_id)


@router.post("/payroll/periods/{period_id}/compute")
@require_permission("payroll.change_payperiod")
def compute_period_endpoint(
    request: Any, period_id: uuid.UUID, payload: ComputePeriodIn
) -> dict[str, Any] | JsonResponse:
    period = _get_period(request, period_id)
    try:
        payslips = compute_period(period, request.auth, employee_ids=payload.employee_ids)
    except ValidationError as exc:
        return _error_response(exc)
    return {"computed": len(payslips)}


@router.post("/payroll/periods/{period_id}/verify")
@require_permission("payroll.change_payperiod")
def verify_period_endpoint(request: Any, period_id: uuid.UUID) -> dict[str, Any] | JsonResponse:
    from apps.payroll.services.approvals import request_period_verification

    period = _get_period(request, period_id)
    try:
        approval = request_period_verification(period, request.auth)
    except ValidationError as exc:
        return _error_response(exc)
    return {"approval_request_id": str(approval.id)}


@router.post("/payroll/periods/{period_id}/validate")
@require_permission("payroll.change_payperiod")
def validate_period_endpoint(request: Any, period_id: uuid.UUID) -> dict[str, Any] | JsonResponse:
    period = _get_period(request, period_id)
    try:
        batch = create_batch(period)
        control_batch(batch, request.auth)
        validate_and_post_batch(batch, request.auth)
    except ValidationError as exc:
        return _error_response(exc)
    return {"batch_id": str(batch.id)}


@router.post("/payroll/periods/{period_id}/pay")
@require_permission("payroll.change_payperiod")
def pay_period_endpoint(request: Any, period_id: uuid.UUID) -> dict[str, Any] | JsonResponse:
    period = _get_period(request, period_id)
    try:
        mark_period_paid(period, request.auth)
    except ValidationError as exc:
        return _error_response(exc)
    return {"state": period.state}


@router.post("/payroll/periods/{period_id}/close")
@require_permission("payroll.change_payperiod")
def close_period_endpoint(request: Any, period_id: uuid.UUID) -> dict[str, Any] | JsonResponse:
    period = _get_period(request, period_id)
    try:
        close_period(period, request.auth)
    except ValidationError as exc:
        return _error_response(exc)
    return {"state": period.state}


@router.get("/payroll/payslips")
@require_permission("payroll.view_paypayslip")
def list_payslips(
    request: Any, period: uuid.UUID | None = None, employee: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    role_codes = user_role_codes(request.auth)
    queryset = PayPayslip.objects.filter(is_active=True)
    if period:
        queryset = queryset.filter(period_id=period)
    if employee:
        queryset = queryset.filter(employee_id=employee)
    if not (role_codes & _STAFF_ROLES):
        own_id = _own_employee_id(request)
        queryset = queryset.filter(employee_id=own_id) if own_id else queryset.none()
    return [_serialize_payslip(p, role_codes, request.auth) for p in queryset]


@router.post("/payroll/payslips/{payslip_id}/recompute")
@require_permission("payroll.change_paypayslip")
def recompute_payslip_endpoint(
    request: Any, payslip_id: uuid.UUID
) -> dict[str, Any] | JsonResponse:
    payslip = get_object_or_404(PayPayslip, id=payslip_id)
    try:
        from apps.payroll.services.periods import ensure_active_contract_for_recompute

        ensure_active_contract_for_recompute(payslip.contract, payslip.period)
        compute_payslip(payslip)
    except ValidationError as exc:
        return _error_response(exc)
    return {"net_to_pay": str(payslip.net_to_pay)}


@router.get("/payroll/payslips/{payslip_id}/pdf")
@require_permission("payroll.view_paypayslip")
def payslip_pdf_endpoint(request: Any, payslip_id: uuid.UUID) -> JsonResponse:
    """RG-PAY-9 (test d'acceptance §5.10.10 n°5) : un `collaborateur`
    n'accede qu'au PDF de SON PROPRE bulletin — 403 explicite sinon (jamais
    un 404, qui laisserait deviner l'existence d'un bulletin d'autrui par
    enumeration d'UUID)."""
    from django.http import HttpResponse

    payslip = get_object_or_404(PayPayslip, id=payslip_id)
    role_codes = user_role_codes(request.auth)
    if not (role_codes & _STAFF_ROLES):
        own_id = _own_employee_id(request)
        if own_id is None or payslip.employee_id != own_id:
            return JsonResponse({"detail": "Acces refuse."}, status=403)
    pdf_bytes = payslip_pdf(payslip)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{payslip.reference}.pdf"'
    return response  # type: ignore[return-value]


@router.get("/payroll/declarations")
@require_permission("payroll.view_paydeclaration")
def list_declarations(
    request: Any, period: uuid.UUID | None = None, type: str | None = None
) -> list[dict[str, Any]]:
    queryset = PayDeclaration.objects.filter(is_active=True)
    if period:
        queryset = queryset.filter(period_id=period)
    if type:
        queryset = queryset.filter(type=type)
    return [
        {"id": str(d.id), "type": d.type, "state": d.state, "amount": d.amount} for d in queryset
    ]


@router.get("/payroll/advances")
@require_permission("payroll.view_payadvance")
def list_advances(request: Any) -> list[dict[str, Any]]:
    role_codes = user_role_codes(request.auth)
    queryset = PayAdvance.objects.filter(is_active=True)
    if not (role_codes & _STAFF_ROLES):
        own_id = _own_employee_id(request)
        queryset = queryset.filter(employee_id=own_id) if own_id else queryset.none()
    return [
        {
            "id": str(a.id),
            "employee_id": str(a.employee_id),
            "amount": a.amount,
            "remaining": a.remaining,
            "state": a.state,
        }
        for a in queryset
    ]


@router.post("/payroll/advances")
@require_permission("payroll.add_payadvance")
def create_advance_endpoint(request: Any, payload: AdvanceIn) -> dict[str, Any] | JsonResponse:
    import datetime as dt

    try:
        advance = request_advance(
            _tenant(request),
            employee_id=payload.employee_id,
            date=dt.date.fromisoformat(payload.date),
            amount=payload.amount,
            reason=payload.reason,
            repayment_months=payload.repayment_months,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return {"id": str(advance.id), "reference": advance.reference}
