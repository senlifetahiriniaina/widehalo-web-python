"""API django-ninja du module `financing` (dossiers de financement bancaire
PME). RBAC scope explicitement a `admin`/`direction`/`comptable` (cf.
`apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS`) — un dossier de
financement bancaire n'est pas une operation courante des autres roles."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import require_permission
from apps.core.services.workflow import TransitionPermissionError
from apps.financing.models import FinCredoc, FinFinancingPlanLine, FinGuarantee, FinLoanApplication
from apps.financing.services.credoc import (
    close_credoc,
    create_credoc,
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

router = Router(tags=["financing"])


class LoanApplicationIn(Schema):
    type: str
    amount_requested_mga: Decimal
    duration_months: int
    purpose: str = ""
    currency: str = "MGA"
    bank_partner_id: str | None = None
    bank_name: str = ""
    own_contribution_pct: Decimal = Decimal(30)


class FinancingPlanLineIn(Schema):
    source: str
    amount_mga: Decimal
    label: str = ""


class DecisionIn(Schema):
    accepted: bool
    rejection_reason: str = ""


class GuaranteeIn(Schema):
    type: str
    estimated_value_mga: Decimal
    asset_description: str = ""


class CredocIn(Schema):
    purchase_order_id: str
    bank: str
    beneficiary: str
    amount_mga: Decimal
    validity_date: str
    currency: str = "MGA"
    advising_bank: str = ""
    log_shipment_id: str | None = None
    incoterm: str = ""
    documents_required: list[str] = []


def _serialize_application(application: FinLoanApplication) -> dict[str, Any]:
    return {
        "id": str(application.id),
        "reference": application.reference,
        "type": application.type,
        "state": application.state,
        "amount_requested_mga": application.amount_requested_mga,
        "currency": application.currency,
        "duration_months": application.duration_months,
        "own_contribution_pct": application.own_contribution_pct,
        "bank_name": application.bank_name,
        "financing_plan_total_mga": financing_plan_total(application),
    }


def _serialize_line(line: FinFinancingPlanLine) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "source": line.source,
        "label": line.label,
        "amount_mga": line.amount_mga,
    }


def _serialize_guarantee(guarantee: FinGuarantee) -> dict[str, Any]:
    return {
        "id": str(guarantee.id),
        "reference": guarantee.reference,
        "type": guarantee.type,
        "asset_description": guarantee.asset_description,
        "estimated_value_mga": guarantee.estimated_value_mga,
        "formalization_status": guarantee.formalization_status,
    }


def _serialize_credoc(credoc: FinCredoc) -> dict[str, Any]:
    return {
        "id": str(credoc.id),
        "reference": credoc.reference,
        "state": credoc.state,
        "purchase_order_id": str(credoc.purchase_order_id),
        "log_shipment_id": str(credoc.log_shipment_id) if credoc.log_shipment_id else None,
        "bank": credoc.bank,
        "advising_bank": credoc.advising_bank,
        "beneficiary": credoc.beneficiary,
        "amount_mga": credoc.amount_mga,
        "currency": credoc.currency,
        "validity_date": credoc.validity_date.isoformat(),
        "incoterm": credoc.incoterm,
        "documents_required": credoc.documents_required,
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT rester le decorateur
# EXTERNE et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`) — meme piege deja documente dans tous les autres `api.py`.
@router.get("/financing/loan-applications")
@require_permission("financing.view_finloanapplication")
def list_loan_applications_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    applications = FinLoanApplication.objects.filter(tenant=tenant, is_active=True)
    return {"results": [_serialize_application(a) for a in applications]}


@router.post("/financing/loan-applications")
@require_permission("financing.add_finloanapplication")
def create_loan_application_endpoint(request: Any, payload: LoanApplicationIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        application = create_loan_application(
            tenant,
            type=payload.type,
            amount_requested_mga=payload.amount_requested_mga,
            duration_months=payload.duration_months,
            purpose=payload.purpose,
            currency=payload.currency,
            bank_partner_id=payload.bank_partner_id,
            bank_name=payload.bank_name,
            own_contribution_pct=payload.own_contribution_pct,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_application(application)


@router.get("/financing/loan-applications/{application_id}")
@require_permission("financing.view_finloanapplication")
def loan_application_detail_endpoint(request: Any, application_id: str) -> dict[str, Any]:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    lines = application.financing_plan_lines.filter(is_active=True)
    return {
        **_serialize_application(application),
        "financing_plan_lines": [_serialize_line(line) for line in lines],
    }


@router.post("/financing/loan-applications/{application_id}/financing-plan-lines")
@require_permission("financing.change_finloanapplication")
def add_financing_plan_line_endpoint(
    request: Any, application_id: str, payload: FinancingPlanLineIn
) -> dict[str, Any]:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    try:
        line = add_financing_plan_line(
            application, source=payload.source, amount_mga=payload.amount_mga, label=payload.label
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_line(line)


@router.post("/financing/loan-applications/{application_id}/submit")
@require_permission("financing.change_finloanapplication")
def submit_loan_application_endpoint(request: Any, application_id: str) -> dict[str, Any]:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    try:
        submit_application(application)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    application.refresh_from_db()
    return _serialize_application(application)


@router.post("/financing/loan-applications/{application_id}/decide")
@require_permission("financing.change_finloanapplication")
def decide_loan_application_endpoint(
    request: Any, application_id: str, payload: DecisionIn
) -> dict[str, Any]:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    try:
        decide_application(
            application, accepted=payload.accepted, rejection_reason=payload.rejection_reason
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    application.refresh_from_db()
    return _serialize_application(application)


@router.get("/financing/loan-applications/{application_id}/guarantees")
@require_permission("financing.view_finguarantee")
def list_guarantees_endpoint(request: Any, application_id: str) -> dict[str, Any]:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    guarantees = application.guarantees.filter(is_active=True)
    coverage = check_guarantee_coverage(application)
    return {
        "results": [_serialize_guarantee(g) for g in guarantees],
        "coverage": coverage,
    }


@router.post("/financing/loan-applications/{application_id}/guarantees")
@require_permission("financing.add_finguarantee")
def add_guarantee_endpoint(
    request: Any, application_id: str, payload: GuaranteeIn
) -> dict[str, Any]:
    application = get_object_or_404(FinLoanApplication, id=application_id)
    try:
        guarantee = add_guarantee(
            application,
            type=payload.type,
            estimated_value_mga=payload.estimated_value_mga,
            asset_description=payload.asset_description,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_guarantee(guarantee)


@router.get("/financing/credocs")
@require_permission("financing.view_fincredoc")
def list_credocs_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    credocs = FinCredoc.objects.filter(tenant=tenant, is_active=True)
    return {"results": [_serialize_credoc(c) for c in credocs]}


@router.post("/financing/credocs")
@require_permission("financing.add_fincredoc")
def create_credoc_endpoint(request: Any, payload: CredocIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        credoc = create_credoc(
            tenant,
            purchase_order_id=payload.purchase_order_id,
            bank=payload.bank,
            beneficiary=payload.beneficiary,
            amount_mga=payload.amount_mga,
            validity_date=dt.date.fromisoformat(payload.validity_date),
            currency=payload.currency,
            advising_bank=payload.advising_bank,
            log_shipment_id=payload.log_shipment_id,
            incoterm=payload.incoterm,
            documents_required=payload.documents_required,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_credoc(credoc)


@router.get("/financing/credocs/{credoc_id}")
@require_permission("financing.view_fincredoc")
def credoc_detail_endpoint(request: Any, credoc_id: str) -> dict[str, Any]:
    credoc = get_object_or_404(FinCredoc, id=credoc_id)
    return _serialize_credoc(credoc)


_CREDOC_TRANSITIONS = {
    "open": open_credoc,
    "receive_documents": receive_documents,
    "pay": pay_credoc,
    "close": close_credoc,
}


class CredocTransitionIn(Schema):
    # B2 : motif desormais obligatoire sur les 4 transitions
    # (`services/credoc.py`) — vide par defaut ici pour laisser le service
    # lever la `ValidationError` i18n habituelle (capturee ci-dessous)
    # plutot qu'un rejet de schema Ninja moins explicite.
    reason: str = ""


@router.post("/financing/credocs/{credoc_id}/transition/{action}")
@require_permission("financing.change_fincredoc")
def transition_credoc_endpoint(
    request: Any, credoc_id: str, action: str, payload: CredocTransitionIn
) -> dict[str, Any]:
    credoc = get_object_or_404(FinCredoc, id=credoc_id)
    transition_fn = _CREDOC_TRANSITIONS.get(action)
    if transition_fn is None:
        return JsonResponse({"detail": "action inconnue"}, status=400)
    user = request.auth
    assert isinstance(user, User)
    try:
        transition_fn(credoc, user, reason=payload.reason)
    except (ValidationError, TransitionPermissionError) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse({"detail": message}, status=400)
    credoc.refresh_from_db()
    return _serialize_credoc(credoc)
