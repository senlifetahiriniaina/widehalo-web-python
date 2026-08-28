from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayAdvance


def request_advance(
    tenant: Tenant,
    *,
    employee_id: UUID,
    date: dt.date,
    amount: Decimal,
    reason: str = "",
    repayment_months: int = 1,
) -> PayAdvance:
    return PayAdvance.objects.create(
        tenant=tenant,
        employee_id=employee_id,
        date=date,
        amount=amount,
        reason=reason,
        repayment_months=repayment_months,
        remaining=amount,
    )


def approve_advance(advance: PayAdvance, user: User) -> PayAdvance:
    attempt_transition(advance, "approve", user)
    advance.save(update_fields=["state"])
    return advance


def reject_advance(advance: PayAdvance, user: User) -> PayAdvance:
    attempt_transition(advance, "reject", user)
    advance.save(update_fields=["state"])
    return advance


def start_repayment(advance: PayAdvance, user: User) -> PayAdvance:
    attempt_transition(advance, "start_repayment", user)
    advance.save(update_fields=["state"])
    return advance


def register_installment(advance: PayAdvance, user: User, *, amount: Decimal) -> PayAdvance:
    """Deduit l'echeance effectivement retenue sur un bulletin — appele par
    `services.payslip.compute_payslip` (indirectement, via la lecture de
    `remaining`/`repayment_months`) UNIQUEMENT une fois le bulletin
    APPROUVE (jamais a chaque recalcul en brouillon, qui resterait
    idempotent — RG-PAY-10)."""
    advance.remaining = max(advance.remaining - amount, Decimal(0))
    advance.save(update_fields=["remaining"])
    if advance.remaining <= 0:
        attempt_transition(advance, "settle", user)
        advance.save(update_fields=["state"])
    return advance
