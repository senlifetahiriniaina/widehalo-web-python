"""PR3 : PRS-COMP1 (matrice de competences)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from apps.presence.models import PrsEmployee, PrsEmployeeSkill

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def set_employee_skill_level(
    employee: PrsEmployee,
    *,
    skill_name: str,
    level: str,
    evaluated_at: dt.date | None = None,
    evaluated_by: User | None = None,
) -> PrsEmployeeSkill:
    skill, _created = PrsEmployeeSkill.objects.update_or_create(
        tenant=employee.tenant,
        employee=employee,
        skill_name=skill_name,
        defaults={
            "level": level,
            "evaluated_at": evaluated_at,
            "evaluated_by": evaluated_by,
        },
    )
    return skill


def find_employees_with_skill(
    tenant: Tenant, *, skill_name: str, min_level: str | None = None
) -> list[PrsEmployeeSkill]:
    """PRS-COMP1 : "qui sait faire quoi" — utilise par l'affectation aux
    ordres de travail (mrp/patronage, hors perimetre direct de ce
    chantier — expose ici, consommable via un futur gap
    `presence.services.public` si le besoin se materialise)."""
    queryset = PrsEmployeeSkill.objects.filter(tenant=tenant, skill_name=skill_name)
    if min_level is not None:
        levels_order = [
            PrsEmployeeSkill.LEVEL_NOVICE,
            PrsEmployeeSkill.LEVEL_INTERMEDIATE,
            PrsEmployeeSkill.LEVEL_CONFIRMED,
            PrsEmployeeSkill.LEVEL_EXPERT,
        ]
        min_index = levels_order.index(min_level)
        acceptable_levels = levels_order[min_index:]
        queryset = queryset.filter(level__in=acceptable_levels)
    return list(queryset.select_related("employee"))
