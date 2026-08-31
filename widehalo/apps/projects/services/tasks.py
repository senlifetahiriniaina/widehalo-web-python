"""Creation de tache et transitions FSM (PJ1, complete PJ7). Cf. docstring
de `apps/projects/models.py` pour le niveau de validation de hierarchie
applique ici (structurel uniquement — un `parent` doit appartenir au meme
projet ; la coherence semantique des types epic/tache/jalon est reportee
a PJ2). PJ7 ajoute la validation de `custom_fields` contre les
`PrjCustomFieldDefinition` du tenant AVANT toute ecriture (cf.
`services/custom_fields.py::validate_custom_fields`)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.projects.models import PrjCustomFieldDefinition, PrjProject, PrjTask
from apps.projects.services.custom_fields import validate_custom_fields


def create_task(
    tenant: Tenant,
    *,
    project: PrjProject,
    task_type: str = PrjTask.TYPE_TASK,
    parent: PrjTask | None = None,
    assignee: User | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    duration_days: int = 0,
    story_points: int | None = None,
    custom_fields: dict[str, Any] | None = None,
) -> PrjTask:
    if parent is not None and parent.project_id != project.id:
        raise ValidationError(
            _("Une tache parente doit appartenir au même projet que la tache créée.")
        )
    validate_custom_fields(tenant, PrjCustomFieldDefinition.ENTITY_TASK, custom_fields)
    reference = next_reference(tenant, "PRJ-TACHE", timezone.now().year)
    return PrjTask.objects.create(
        tenant=tenant,
        reference=reference,
        project=project,
        task_type=task_type,
        parent=parent,
        assignee=assignee,
        start_date=start_date,
        end_date=end_date,
        duration_days=duration_days,
        story_points=story_points,
        custom_fields=custom_fields or {},
    )


def start_task(task: PrjTask, user: User) -> PrjTask:
    attempt_transition(task, "start", user)
    task.save(update_fields=["state"])
    return task


def block_task(task: PrjTask, user: User) -> PrjTask:
    attempt_transition(task, "block", user)
    task.save(update_fields=["state"])
    return task


def unblock_task(task: PrjTask, user: User) -> PrjTask:
    attempt_transition(task, "unblock", user)
    task.save(update_fields=["state"])
    return task


def finish_task(task: PrjTask, user: User) -> PrjTask:
    attempt_transition(task, "finish", user)
    task.percent_complete = 100
    task.save(update_fields=["state", "percent_complete"])
    return task


def cancel_task(task: PrjTask, user: User) -> PrjTask:
    attempt_transition(task, "cancel", user)
    task.save(update_fields=["state"])
    return task
