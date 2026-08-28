"""PR3 : PRS-ONB1 (cycle d'integration nouvel employe). Meme patron que
`apps.partners.services.onboarding` (checklist declenchee a la creation)
transpose a l'embauche. **Simplification disclosed** : la checklist type
(`DEFAULT_ONBOARDING_STEPS`) est definie en Python, pas parametrable en
base par le tenant en V1 — un vrai parametrage par tenant demanderait un
nouveau modele de template, hors budget (170/180 a la cloture de
`logistics`, cf. `apps/presence/models.py`)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, NamedTuple

from django.utils import timezone

from apps.presence.models import PrsEmployee, PrsEmployeeTask

if TYPE_CHECKING:
    from apps.core.models.user import User


class OnboardingStepTemplate(NamedTuple):
    code: str
    label: str
    default_due_days: int


# Etapes suggerees par le CDC (§5.9.9, enrichissement "Adapter") :
# contrat, declaration CNaPS, poste, comptes, equipement, formation
# securite.
DEFAULT_ONBOARDING_STEPS: list[OnboardingStepTemplate] = [
    OnboardingStepTemplate("contrat", "Signature du contrat de travail", 0),
    OnboardingStepTemplate("cnaps", "Déclaration CNaPS/OSTIE", 7),
    OnboardingStepTemplate("poste", "Installation au poste de travail", 1),
    OnboardingStepTemplate("comptes", "Création des comptes applicatifs", 1),
    OnboardingStepTemplate("equipement", "Remise des équipements/EPI", 1),
    OnboardingStepTemplate("formation_securite", "Formation sécurité", 14),
]


def trigger_onboarding_checklist(
    employee: PrsEmployee,
    *,
    responsible: User | None = None,
    steps: list[OnboardingStepTemplate] | None = None,
) -> list[PrsEmployeeTask]:
    """Declenchee a l'embauche — idempotent (un `code` deja present pour
    cet employe n'est jamais duplique)."""
    tasks: list[PrsEmployeeTask] = []
    for step in steps or DEFAULT_ONBOARDING_STEPS:
        task, _created = PrsEmployeeTask.objects.get_or_create(
            tenant=employee.tenant,
            employee=employee,
            kind=PrsEmployeeTask.KIND_ONBOARDING,
            code=step.code,
            defaults={
                "label": step.label,
                "target_date": employee.hire_date + dt.timedelta(days=step.default_due_days),
                "responsible": responsible,
            },
        )
        tasks.append(task)
    return tasks


def complete_onboarding_task(task: PrsEmployeeTask, *, completed_by: User) -> PrsEmployeeTask:
    task.completed_at = timezone.now()
    task.completed_by = completed_by
    task.save(update_fields=["completed_at", "completed_by"])
    return task


def onboarding_progress(employee: PrsEmployee) -> tuple[int, int]:
    """Retourne (nombre de taches terminees, nombre total) — utilise par
    l'ecran de suivi RH."""
    tasks = PrsEmployeeTask.objects.filter(
        tenant=employee.tenant, employee=employee, kind=PrsEmployeeTask.KIND_ONBOARDING
    )
    total = tasks.count()
    done = tasks.filter(completed_at__isnull=False).count()
    return done, total
