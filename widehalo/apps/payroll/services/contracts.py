"""RG-PAY-6 : gestion des contrats et de leurs avenants. Le contrat ACTIF a
la date de la periode determine la structure salariale utilisee pour le
calcul du bulletin (RG-PAY-1)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayContract, PayContractType, PaySalaryStructure


def create_contract(
    *,
    tenant: Tenant,
    employee_id: UUID,
    contract_type: PayContractType,
    date_start: dt.date,
    wage_base: Decimal,
    salary_structure: PaySalaryStructure,
    wage_type: str = PayContract.WAGE_MONTHLY,
    date_end: dt.date | None = None,
    job_title: str = "",
    department_id: UUID | None = None,
    workshop_id: UUID | None = None,
    work_calendar_id: UUID | None = None,
    notice_days: int | None = None,
    parent_contract: PayContract | None = None,
) -> PayContract:
    if date_end and date_end < date_start:
        raise ValidationError(_("La date de fin ne peut pas precéder la date de debut."))
    return PayContract.objects.create(
        tenant=tenant,
        employee_id=employee_id,
        type=contract_type,
        date_start=date_start,
        date_end=date_end,
        job_title=job_title,
        department_id=department_id,
        workshop_id=workshop_id,
        wage_base=wage_base,
        wage_type=wage_type,
        work_calendar_id=work_calendar_id,
        salary_structure=salary_structure,
        notice_days=(notice_days if notice_days is not None else contract_type.default_notice_days),
        parent_contract=parent_contract,
    )


def create_amendment(
    original: PayContract, *, date_start: dt.date, **overrides: object
) -> PayContract:
    """RG-PAY-6 : un avenant est un contrat ENFANT (`parent_contract`),
    l'original conserve son historique tel quel — jamais de modification en
    place du contrat d'origine."""
    fields = {
        "tenant": original.tenant,
        "employee_id": original.employee_id,
        "type": original.type,
        "date_start": date_start,
        "date_end": original.date_end,
        "job_title": original.job_title,
        "department_id": original.department_id,
        "workshop_id": original.workshop_id,
        "wage_base": original.wage_base,
        "wage_type": original.wage_type,
        "work_calendar_id": original.work_calendar_id,
        "salary_structure": original.salary_structure,
        "notice_days": original.notice_days,
    }
    fields.update(overrides)
    fields["parent_contract"] = original
    return PayContract.objects.create(**fields)


def activate_contract(contract: PayContract, user: User) -> PayContract:
    attempt_transition(contract, "activate", user)
    contract.save(update_fields=["state"])
    return contract


def end_contract(contract: PayContract, user: User, *, date_end: dt.date) -> PayContract:
    contract.date_end = date_end
    attempt_transition(contract, "end", user)
    contract.save(update_fields=["state", "date_end"])
    return contract


def resolve_active_contract(
    tenant: Tenant, employee_id: UUID, *, at_date: dt.date
) -> PayContract | None:
    """RG-PAY-6 : contrat ACTIF a `at_date` — parmi ceux dont
    `date_start <= at_date <= (date_end ou +infini)`, prend le plus recent
    (`date_start` le plus proche de `at_date`), qui est la version la plus
    a jour d'une eventuelle chaine d'avenants."""
    return (
        PayContract.objects.filter(
            tenant=tenant,
            employee_id=employee_id,
            state=PayContract.STATE_ACTIVE,
            date_start__lte=at_date,
        )
        .filter(Q(date_end__isnull=True) | Q(date_end__gte=at_date))
        .order_by("-date_start")
        .first()
    )
