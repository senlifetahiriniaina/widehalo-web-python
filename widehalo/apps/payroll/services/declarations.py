"""PAY-IRSA/PAY-CNAPS/PAY-OSTIE (§5.10.8) : etat de declaration genere a
partir des bulletins VALIDES d'une periode — un seul `PayDeclaration` par
(periode, type)."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayDeclaration, PayPayslip, PayPeriod


def generate_declaration(period: PayPeriod, declaration_type: str) -> PayDeclaration:
    payslips = period.payslips.exclude(state=PayPayslip.STATE_CANCELLED)
    total = Decimal(0)
    if declaration_type == PayDeclaration.TYPE_IRSA:
        total = sum((p.irsa for p in payslips), Decimal(0))
    elif declaration_type == PayDeclaration.TYPE_CNAPS:
        for p in payslips:
            for amount in p.lines.filter(code__in=["CNAPS_SAL", "CNAPS_PAT"]).values_list(
                "amount", flat=True
            ):
                total += amount
    elif declaration_type == PayDeclaration.TYPE_OSTIE:
        for p in payslips:
            for amount in p.lines.filter(code__in=["OSTIE_SAL", "OSTIE_PAT"]).values_list(
                "amount", flat=True
            ):
                total += amount

    declaration, _created = PayDeclaration.objects.update_or_create(
        tenant=period.tenant,
        period=period,
        type=declaration_type,
        defaults={"amount": total},
    )
    return declaration


def submit_declaration(declaration: PayDeclaration, user: User) -> PayDeclaration:
    attempt_transition(declaration, "submit", user)
    declaration.submitted_at = timezone.now()
    declaration.save(update_fields=["state", "submitted_at"])
    return declaration
