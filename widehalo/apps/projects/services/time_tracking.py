"""Suivi du temps passe sur les taches (PJ8) — cf. plan, section « Module
`projects` », etape PJ8. Comble le gap explicitement annonce depuis PJ5
(`services/billing.py::bill_time_and_material`, STUB HONNETE en attendant
`PrjTimeEntry`).

**Regle du chrono unique, disclosed explicitement** : un utilisateur ne
peut avoir qu'UN SEUL chrono actif a la fois (tous projets/taches
confondus) — une entree `PrjTimeEntry` avec `stopped_at=None` EST, par
definition, le chrono actif de son `user`. `start_timer` refuse
explicitement (leve `ValidationError`) toute seconde tentative tant qu'une
telle entree existe deja pour ce `user` — regle simple et VOLONTAIREMENT
PAS une verification de chevauchement d'intervalles entre plusieurs
saisies MANUELLES (`log_manual_time_entry`), qui restent, elles, non
gardees contre le chevauchement (disclosed comme hors perimetre : deux
saisies manuelles peuvent techniquement se chevaucher).

`stop_timer` refuse (leve `ValidationError`) si l'entree est deja arretee
(`stopped_at` deja renseigne) OU si l'appelant n'est pas le `user`
proprietaire du chrono (RBAC N3 : "un utilisateur ne peut arreter que SON
PROPRE chrono", jamais celui d'un collegue — cf. `apps/projects/api.py`
pour le branchement RBAC complet)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.projects.models import PrjProject, PrjTask, PrjTimeEntry

_MINUTES_PER_HOUR = Decimal(60)


def _duration_minutes(started_at: dt.datetime, stopped_at: dt.datetime) -> int:
    if stopped_at <= started_at:
        raise ValidationError(
            _("La date/heure de fin doit etre strictement posterieure a la date/heure de debut.")
        )
    delta = stopped_at - started_at
    return max(1, round(delta.total_seconds() / 60))


def start_timer(task: PrjTask, user: User) -> PrjTimeEntry:
    """Demarre un chrono facturable sur `task` pour `user` — refuse
    (`ValidationError`) si `user` a deja un chrono en cours ailleurs, cf.
    docstring de module."""
    already_running = PrjTimeEntry.objects.filter(user=user, stopped_at__isnull=True).exists()
    if already_running:
        raise ValidationError(
            _(
                "Un chrono est deja en cours pour cet utilisateur : "
                "arretez-le avant d'en demarrer un autre."
            )
        )
    return PrjTimeEntry.objects.create(
        tenant=task.tenant,
        task=task,
        user=user,
        started_at=timezone.now(),
        stopped_at=None,
    )


def stop_timer(time_entry: PrjTimeEntry, user: User) -> PrjTimeEntry:
    """Arrete le chrono `time_entry` et calcule `duration_minutes` — refuse
    si deja arrete ou si `user` n'est pas le proprietaire du chrono, cf.
    docstring de module."""
    if time_entry.user_id != user.id:
        raise ValidationError(_("Vous ne pouvez arreter que votre propre chrono."))
    if time_entry.stopped_at is not None:
        raise ValidationError(_("Ce chrono est deja arrete."))
    stopped_at = timezone.now()
    time_entry.stopped_at = stopped_at
    time_entry.duration_minutes = _duration_minutes(time_entry.started_at, stopped_at)
    time_entry.save(update_fields=["stopped_at", "duration_minutes"])
    return time_entry


def log_manual_time_entry(
    task: PrjTask,
    user: User,
    *,
    started_at: dt.datetime,
    stopped_at: dt.datetime,
    billable: bool = True,
    note: str = "",
) -> PrjTimeEntry:
    """Saisie manuelle a posteriori (sans chrono) — calcule `duration_
    minutes` directement a partir du creneau fourni. Non gardee contre le
    chevauchement d'autres entrees, cf. docstring de module."""
    duration_minutes = _duration_minutes(started_at, stopped_at)
    return PrjTimeEntry.objects.create(
        tenant=task.tenant,
        task=task,
        user=user,
        started_at=started_at,
        stopped_at=stopped_at,
        duration_minutes=duration_minutes,
        billable=billable,
        note=note,
    )


def get_time_report(
    project: PrjProject,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[dict[str, Any]]:
    """Agrege les `PrjTimeEntry` des taches de `project`, groupees par
    utilisateur. Ne considere que les entrees ARRETEES (`stopped_at`
    renseigne — un chrono en cours n'a pas encore de `duration_minutes`
    fiable a agreger). Filtre optionnel sur `started_at__date` (bornes
    inclusives des deux cotes).

    Retourne une liste de dict, un par utilisateur ayant au moins une
    entree, tries par `user_id` :
    `{"user_id": UUID, "total_minutes": int, "billable_minutes": int,
    "billed_minutes": int}`."""
    entries = PrjTimeEntry.objects.filter(
        task__project=project, is_active=True, stopped_at__isnull=False
    )
    if date_from is not None:
        entries = entries.filter(started_at__date__gte=date_from)
    if date_to is not None:
        entries = entries.filter(started_at__date__lte=date_to)

    report_by_user: dict[Any, dict[str, Any]] = {}
    for entry in entries.order_by("user_id"):
        bucket = report_by_user.setdefault(
            entry.user_id,
            {
                "user_id": entry.user_id,
                "total_minutes": 0,
                "billable_minutes": 0,
                "billed_minutes": 0,
            },
        )
        bucket["total_minutes"] += entry.duration_minutes
        if entry.billable:
            bucket["billable_minutes"] += entry.duration_minutes
        if entry.billed:
            bucket["billed_minutes"] += entry.duration_minutes
    return list(report_by_user.values())


def get_unbilled_billable_hours(project: PrjProject) -> Decimal:
    """Heures facturables (`billable=True`) non encore facturees
    (`billed=False`) des taches de `project` — alimente `services/
    billing.py::bill_time_and_material`."""
    total_minutes = (
        PrjTimeEntry.objects.filter(
            task__project=project,
            is_active=True,
            stopped_at__isnull=False,
            billable=True,
            billed=False,
        ).aggregate(total=Sum("duration_minutes"))["total"]
        or 0
    )
    return Decimal(total_minutes) / _MINUTES_PER_HOUR
