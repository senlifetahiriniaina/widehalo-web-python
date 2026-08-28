"""Contrat public de l'app `presence` — seule surface que d'autres apps
(futur module Paie, notamment RG-PAY-1 qui cite ce module comme point de
depart de la chaine de calcul) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py). Etoffe au fil des PR de ce
chantier (PR2 : soldes/absences ; PR4 : heures sup)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Sum

from apps.presence.models import PrsAbsence, PrsEmployee, PrsLeaveBalance, PrsOvertime

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def get_employee_id_for_user(tenant: Tenant, user: User) -> UUID | None:
    """Resout l'employe `presence` associe a un compte applicatif — utilise
    notamment pour le scoping RBAC N3 "own" (RG-PRS-9, test d'acceptance
    §5.9.8 n°4)."""
    employee = PrsEmployee.objects.filter(tenant=tenant, user=user, is_active=True).first()
    return employee.id if employee else None


def is_employee_active(tenant: Tenant, employee_id: UUID) -> bool:
    return PrsEmployee.objects.filter(tenant=tenant, id=employee_id, is_active=True).exists()


def get_leave_balance_remaining_days(
    tenant: Tenant, employee_id: UUID, *, year: int, absence_type_code: str
) -> Decimal | None:
    """Gap prepare pour le futur module Paie (RG-PAY-1 : cite `presence`
    comme point de depart de la chaine de calcul) — solde restant d'un
    employe pour un type d'absence donne. Retourne None si aucun solde
    n'existe encore pour cette combinaison (jamais 0 par defaut, qui
    serait une fausse certitude)."""
    balance = PrsLeaveBalance.objects.filter(
        tenant=tenant, employee_id=employee_id, year=year, type__code=absence_type_code
    ).first()
    return balance.remaining_days if balance else None


def get_validated_overtime_hours(
    tenant: Tenant, employee_id: UUID, *, date_from: dt.date, date_to: dt.date
) -> Decimal:
    """Gap prepare pour le futur module Paie : total des heures sup
    VALIDEES (jamais brouillon) sur une periode, toutes categories de
    majoration confondues — le detail par categorie reste consultable via
    l'API `presence` elle-meme si le futur module Paie en a besoin."""
    total = PrsOvertime.objects.filter(
        tenant=tenant,
        employee_id=employee_id,
        date__gte=date_from,
        date__lte=date_to,
        state=PrsOvertime.STATE_VALIDATED,
    ).aggregate(total=Sum("hours"))["total"]
    return total if total is not None else Decimal(0)


def is_employee_absent_on(tenant: Tenant, employee_id: UUID, *, date: dt.date) -> bool:
    """Gap prepare pour le futur module Paie : un employe est considere
    absent ce jour si une `PrsAbsence` validee/en cours/terminee couvre
    cette date (jamais une absence encore en attente de validation)."""
    return PrsAbsence.objects.filter(
        tenant=tenant,
        employee_id=employee_id,
        date_from__lte=date,
        date_to__gte=date,
        state__in=[
            PrsAbsence.STATE_VALIDATED,
            PrsAbsence.STATE_IN_PROGRESS,
            PrsAbsence.STATE_DONE,
        ],
    ).exists()
