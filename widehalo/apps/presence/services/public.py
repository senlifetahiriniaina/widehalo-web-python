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

from apps.presence.models import (
    PrsAbsence,
    PrsDepartment,
    PrsEmployee,
    PrsLeaveBalance,
    PrsOvertime,
)

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


def get_period_absence_summary(
    tenant: Tenant, employee_id: UUID, *, date_from: dt.date, date_to: dt.date
) -> list[dict[str, object]]:
    """Nouveau gap ajoute pendant le chantier `payroll` (RG-PAY-1/RG-PAY-4 :
    chaque type d'absence porte son taux de remuneration, `PrsAbsenceType.
    pay_rate_pct`) — les 4 gaps preexistants (`is_employee_absent_on`
    notamment) ne renvoient qu'un booleen jour par jour, insuffisant pour
    ventiler `pay_payslip.absence_days` PAR CATEGORIE avec son taux. Meme
    patron que les gaps existants : seules des absences VALIDEES/en cours/
    terminees comptent (jamais brouillon/soumise), primitives en sortie
    (jamais un objet `PrsAbsence`).

    Retourne une liste `{"category": str, "days": Decimal, "pay_rate_pct":
    Decimal}` — une entree par (categorie, taux) rencontres, agregee, chaque
    absence etant clippee a l'intersection avec `[date_from, date_to]`.
    **Simplification assumee** : le nombre de jours clippe recalcule un
    prorata lineaire sur l'intersection (jamais les demi-journees
    `half_day_start`/`half_day_end` d'origine, qui ne sont pas reconstituables
    proportionnellement une fois l'absence tronquee) — dette mineure
    disclosed, un ecart de detail sur des bordures de periode seulement."""
    absences = PrsAbsence.objects.filter(
        tenant=tenant,
        employee_id=employee_id,
        date_from__lte=date_to,
        date_to__gte=date_from,
        state__in=[
            PrsAbsence.STATE_VALIDATED,
            PrsAbsence.STATE_IN_PROGRESS,
            PrsAbsence.STATE_DONE,
        ],
    ).select_related("type")
    totals: dict[tuple[str, str], Decimal] = {}
    for absence in absences:
        clipped_from = max(absence.date_from, date_from)
        clipped_to = min(absence.date_to, date_to)
        if clipped_to < clipped_from:
            continue
        clipped_days = Decimal((clipped_to - clipped_from).days + 1)
        key = (absence.type.category, str(absence.type.pay_rate_pct))
        totals[key] = totals.get(key, Decimal(0)) + clipped_days
    return [
        {"category": category, "pay_rate_pct": Decimal(rate), "days": days}
        for (category, rate), days in totals.items()
    ]


def get_department_display_name(tenant: Tenant, department_id: UUID) -> str | None:
    """Nouveau gap ajoute pendant le chantier `strategy` (`StgObjective.
    department_id` reference un departement `presence` par UUID, jamais une
    FK Django — regle de couplage n°1). Retourne `None` si le departement
    n'existe pas/plus (jamais une chaine vide qui masquerait l'absence de
    donnee)."""
    department = PrsDepartment.objects.filter(tenant=tenant, id=department_id).first()
    return department.name if department else None


def get_department_ids_managed_by(tenant: Tenant, user: User) -> list[UUID]:
    """Nouveau gap ajoute pendant le chantier `strategy` (RBAC N3 : un
    responsable de departement ne gere QUE les objectifs departement de son
    ou ses propres departements, cf. `apps.strategy.services.scoping`) —
    tous les `PrsDepartment` dont `user` est `manager`."""
    return list(
        PrsDepartment.objects.filter(tenant=tenant, manager=user).values_list("id", flat=True)
    )


def get_tenant_absence_days_in_period(
    tenant: Tenant, *, date_from: dt.date, date_to: dt.date
) -> Decimal:
    """Gap ajoute pour le chantier « capacite de charge a 90 jours »
    (CAP1-2, cf. plan) : `strategy.services.capacity_review` a besoin d'un
    volume d'absences TENANT-WIDE sur une fenetre (pas par employe comme
    `get_period_absence_summary`, qui exige un `employee_id` et n'a donc
    pas vocation a etre appele une fois par employe pour construire un
    indicateur global) — aucun gap equivalent n'existait avant ce
    chantier.

    Meme discipline que `get_period_absence_summary` : seules les absences
    VALIDEES/en cours/terminees comptent (jamais brouillon/soumise), et
    chaque absence est clippee a l'intersection avec `[date_from,
    date_to]` (meme simplification assumee — prorata lineaire, pas les
    demi-journees d'origine). Retourne un total en jours-personne toutes
    categories confondues (le detail par categorie reste disponible via
    `get_period_absence_summary` pour un employe donne si necessaire) —
    `Decimal(0)` si aucune absence, jamais une exception."""
    absences = PrsAbsence.objects.filter(
        tenant=tenant,
        date_from__lte=date_to,
        date_to__gte=date_from,
        state__in=[
            PrsAbsence.STATE_VALIDATED,
            PrsAbsence.STATE_IN_PROGRESS,
            PrsAbsence.STATE_DONE,
        ],
    )
    total = Decimal(0)
    for absence in absences:
        clipped_from = max(absence.date_from, date_from)
        clipped_to = min(absence.date_to, date_to)
        if clipped_to < clipped_from:
            continue
        total += Decimal((clipped_to - clipped_from).days + 1)
    return total


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
