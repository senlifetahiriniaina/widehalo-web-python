"""Workflow §5.10.7 d'une periode de paie : ouverte -> en_calcul -> verifiee
-> validee -> payee -> cloturee (+ recalcul tant que non validee). Chaque
transition passe par `attempt_transition()` + `.save(update_fields=...)`
IMMEDIATEMENT — garde-fou AST `tests/architecture/
test_attempt_transition_saves_state.py`."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayContract, PayPayslip, PayPeriod
from apps.payroll.services.contracts import resolve_active_contract
from apps.payroll.services.payslip import compute_payslip


def create_period(
    tenant: Tenant, *, code: str, date_from: dt.date, date_to: dt.date, payment_date: dt.date
) -> PayPeriod:
    return PayPeriod.objects.create(
        tenant=tenant, code=code, date_from=date_from, date_to=date_to, payment_date=payment_date
    )


def compute_period(
    period: PayPeriod,
    user: User,
    *,
    employee_ids: list[UUID],
    dependents_by_employee: dict[UUID, int] | None = None,
) -> list[PayPayslip]:
    """RG-PAY-6 : resout, pour chaque employe, le contrat ACTIF a la date
    de la periode — un employe sans contrat actif a cette date est
    silencieusement omis (pas une erreur de calcul de periode, un gap de
    configuration RH a la charge de l'appelant, meme discipline que les
    gaps `accounting.services.public`)."""
    attempt_transition(period, "start_compute", user)
    period.save(update_fields=["state"])

    dependents_by_employee = dependents_by_employee or {}
    payslips: list[PayPayslip] = []
    for employee_id in employee_ids:
        contract = resolve_active_contract(period.tenant, employee_id, at_date=period.date_from)
        if contract is None:
            continue
        payslip, _created = PayPayslip.objects.update_or_create(
            tenant=period.tenant,
            employee_id=employee_id,
            period=period,
            defaults={
                "contract": contract,
                "date_from": period.date_from,
                "date_to": period.date_to,
            },
        )
        compute_payslip(payslip, dependents=dependents_by_employee.get(employee_id, 0))
        _mark_payslip_computed(payslip, user)
        payslips.append(payslip)
    return payslips


def _mark_payslip_computed(payslip: PayPayslip, user: User) -> None:
    """Extrait en fonction dediee (parametre EXPLICITEMENT annote) plutot
    qu'inline dans la boucle de `compute_period` : le garde-fou AST
    `tests/architecture/test_attempt_transition_saves_state.py` ne resout
    le modele FSM concerne que via l'annotation de type d'un PARAMETRE de
    fonction, jamais une simple variable de boucle — meme patron de
    contournement necessaire pour `mark_period_paid` ci-dessous."""
    attempt_transition(payslip, "mark_computed", user)
    payslip.save(update_fields=["state"])


def verify_period(period: PayPeriod, user: User) -> PayPeriod:
    attempt_transition(period, "verify", user)
    period.save(update_fields=["state"])
    return period


def validate_period(period: PayPeriod, user: User) -> PayPeriod:
    """RG-PAY-10 : au-dela de cette transition, plus aucun bulletin de
    cette periode ne peut etre recalcule en place — cf.
    `services.batches.control_and_validate_batch`, qui appelle cette
    fonction apres les 7 controles PAY-CTRL1."""
    if period.state != PayPeriod.STATE_VERIFIED:
        raise ValidationError(_("La periode doit etre verifiee avant validation."))
    attempt_transition(period, "validate", user)
    period.save(update_fields=["state"])
    return period


def mark_period_paid(period: PayPeriod, user: User) -> PayPeriod:
    attempt_transition(period, "mark_paid", user)
    period.save(update_fields=["state"])
    for payslip in period.payslips.filter(state=PayPayslip.STATE_APPROVED):
        _mark_payslip_paid(payslip, user)
    return period


def _mark_payslip_paid(payslip: PayPayslip, user: User) -> None:
    attempt_transition(payslip, "mark_paid", user)
    payslip.save(update_fields=["state"])


def close_period(period: PayPeriod, user: User) -> PayPeriod:
    attempt_transition(period, "close", user)
    period.save(update_fields=["state"])
    return period


def ensure_active_contract_for_recompute(contract: PayContract, period: PayPeriod) -> None:
    """RG-PAY-10 : refuse tout recalcul si la periode est deja VALIDEE (ou
    au-dela) — une correction doit passer par un bulletin RECTIFICATIF."""
    if period.state in (PayPeriod.STATE_VALIDATED, PayPeriod.STATE_PAID, PayPeriod.STATE_CLOSED):
        raise ValidationError(
            _("Periode %(code)s deja validee : recalcul en place interdit (RG-PAY-10).")
            % {"code": period.code}
        )
