"""Gestion d'equipe projet et heatmap de capacite (PJ7). Patron de
composition inspire de `apps.strategy.services.capacity_review::
build_capacity_outlook` (meme decoupage en semaines glissantes,
memes primitives `Decimal`/`date`/`int` en sortie, jamais un objet metier
d'un autre module) — **PAS reutilise tel quel** : ce chantier agrege la
capacite de PERSONNES sur des PROJETS (`PrjTeamMember`/`PrjTask.assignee`),
un domaine different de la capacite ATELIER de `mrp` agregee par
`build_capacity_outlook`. Service pur, aucune notification (contrairement
a `capacity_review`, aucun seuil de surcharge tenant-wide n'est demande ici
— l'indicateur `is_overallocated` est une donnee de LECTURE affichee a
l'ecran, pas un declencheur automatique).

**Garde-fou de sur-allocation — disclosed comme volontairement simple**
(cf. docstring de `PrjTeamMember`) : `add_team_member` compare la SOMME
DECLAREE des `allocation_pct` (jamais une verification de disponibilite
reelle jour par jour croisant les dates des taches) — un garde-fou a la
CREATION d'une affectation, pas une contrainte perpetuelle revalidee a
chaque lecture."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.projects.models import PrjProject, PrjTask, PrjTeamMember
from apps.projects.services.conflicts import dates_overlap

_WEEK_DAYS = 7
DEFAULT_HORIZON_WEEKS = 12

_ACTIVE_TASK_STATES_EXCLUDED = {PrjTask.STATE_DONE, PrjTask.STATE_CANCELLED}


def _total_allocation_pct(user: User, *, exclude_project_id: Any = None) -> int:
    """Somme des `allocation_pct` de toutes les affectations ACTIVES de
    `user`, sur des projets eux-memes ACTIFS (`is_active=True` sur les deux
    modeles — soft-delete applicatif deja en place partout dans ce depot,
    cf. `BaseModel`). `exclude_project_id` permet de recalculer la somme
    "hors ce projet" (utile pour re-verifier apres coup, ex. tests)."""
    qs = PrjTeamMember.objects.filter(user=user, is_active=True, project__is_active=True)
    if exclude_project_id is not None:
        qs = qs.exclude(project_id=exclude_project_id)
    total = qs.values_list("allocation_pct", flat=True)
    return sum(total, start=0)


def add_team_member(
    project: PrjProject, user: User, *, role: str = "", allocation_pct: int
) -> PrjTeamMember:
    """Affecte `user` a `project`. Refuse (leve `ValidationError`, jamais
    une creation silencieuse qui sur-engagerait la personne) si :
    - `allocation_pct` hors `[0, 100]` ;
    - `user` est deja membre ACTIF de `project` (message explicite AVANT la
      `UniqueConstraint(project, user)`, meme discipline que
      `PrjTaskDependency::add_dependency`) ;
    - la somme des `allocation_pct` de TOUS les projets ACTIFS de `user`
      (cf. `_total_allocation_pct`), ajoutee a `allocation_pct`, depasserait
      100 — cf. disclosure de tete de module : une garde DECLARATIVE, pas
      une verification de disponibilite reelle jour par jour.

    **Reactivation plutot que double ligne** (cf. docstring de
    `PrjTeamMember` : `UniqueConstraint(project, user)` simple, PAS une
    contrainte partielle) : si une affectation SOFT-SUPPRIMEE existe deja
    pour ce couple (`remove_team_member` prealablement appele), elle est
    REACTIVEE (role/allocation mis a jour, `is_active=True`,
    `archived_at=None`) plutot que d'en creer une seconde, qui violerait la
    contrainte DB."""
    if not (0 <= allocation_pct <= 100):
        raise ValidationError(_("L'allocation doit être comprise entre 0 et 100%."))
    existing = PrjTeamMember.objects.filter(project=project, user=user).first()
    if existing is not None and existing.is_active:
        raise ValidationError(_("Cet utilisateur est déjà membre de ce projet."))
    current_total = _total_allocation_pct(user)
    if current_total + allocation_pct > 100:
        raise ValidationError(
            _(
                "Sur-allocation refusée : %(user)s a déjà %(current)s%% alloues sur "
                "d'autres projets actifs, +%(added)s%% depasserait 100%%."
            )
            % {"user": user, "current": current_total, "added": allocation_pct}
        )
    if existing is not None:
        existing.role = role
        existing.allocation_pct = allocation_pct
        existing.is_active = True
        existing.archived_at = None
        existing.save(update_fields=["role", "allocation_pct", "is_active", "archived_at"])
        return existing
    return PrjTeamMember.objects.create(
        tenant=project.tenant,
        project=project,
        user=user,
        role=role,
        allocation_pct=allocation_pct,
    )


def remove_team_member(member: PrjTeamMember) -> None:
    """Retrait d'un membre — soft-delete applicatif (`BaseModel.soft_
    delete`), jamais un DELETE SQL, meme discipline que tout le reste de ce
    depot (cf. `ROLE_APP_PERMISSIONS`, "delete" volontairement absent)."""
    member.soft_delete()


def _week_windows(*, start: dt.date, horizon_weeks: int) -> list[tuple[dt.date, dt.date]]:
    """Semaines de 7 jours PLEINES a partir d'aujourd'hui (contrairement a
    `strategy.services.capacity_review::_week_windows`, qui decoupe un
    horizon en JOURS potentiellement non multiple de 7 — ici l'horizon est
    directement exprime en semaines, jamais de derniere semaine
    partielle)."""
    windows: list[tuple[dt.date, dt.date]] = []
    for index in range(horizon_weeks):
        week_start = start + dt.timedelta(days=index * _WEEK_DAYS)
        week_end = week_start + dt.timedelta(days=_WEEK_DAYS - 1)
        windows.append((week_start, week_end))
    return windows


def compute_user_workload_heatmap(
    user: User, *, horizon_weeks: int = DEFAULT_HORIZON_WEEKS, today: dt.date | None = None
) -> list[dict[str, Any]]:
    """Heatmap de capacite d'un utilisateur sur `horizon_weeks` semaines
    pleines a partir d'aujourd'hui. Pour chaque semaine, retourne :
    `{"week_start": date, "week_end": date, "allocation_pct": int,
    "active_task_count": int, "is_overallocated": bool}`.

    - `allocation_pct` : somme DECLAREE des `PrjTeamMember.allocation_pct`
      actifs de l'utilisateur (identique pour chaque semaine de l'horizon —
      c'est une allocation ANNONCEE, pas une donnee qui varie semaine par
      semaine ; repetee sur chaque ligne pour que la heatmap reste
      lisible/exploitable sans jointure supplementaire cote appelant).
    - `active_task_count` : nombre de `PrjTask` assignees a l'utilisateur,
      hors etats terminaux (`done`/`cancelled`), dont l'intervalle
      `[start_date, end_date]` CHEVAUCHE la semaine (reutilise
      `services/conflicts.py::dates_overlap`, meme arithmetique que la
      detection de conflits PJ3, jamais dupliquee) — une tache sans dates
      ne peut chevaucher aucune semaine, ignoree comme dans PJ3.
    - `is_overallocated` : `allocation_pct > 100` — recalcule a CHAQUE
      lecture (contrairement au garde de creation d'`add_team_member`, qui
      ne s'applique qu'au moment de l'ajout) : detecte une derive
      post-creation (allocation editee directement, projet reactive apres
      avoir ete desactive, etc.) plutot que de supposer que la garde de
      creation reste vraie pour toujours."""
    today = today or dt.date.today()
    declared_allocation_pct = _total_allocation_pct(user)

    tasks = [
        task
        for task in PrjTask.objects.filter(assignee=user, is_active=True).exclude(
            state__in=_ACTIVE_TASK_STATES_EXCLUDED
        )
        if task.start_date is not None and task.end_date is not None
    ]

    heatmap: list[dict[str, Any]] = []
    for week_start, week_end in _week_windows(start=today, horizon_weeks=horizon_weeks):
        active_task_count = 0
        for task in tasks:
            assert task.start_date is not None and task.end_date is not None  # filtre ci-dessus
            if dates_overlap(task.start_date, task.end_date, week_start, week_end):
                active_task_count += 1
        heatmap.append(
            {
                "week_start": week_start,
                "week_end": week_end,
                "allocation_pct": declared_allocation_pct,
                "active_task_count": active_task_count,
                "is_overallocated": declared_allocation_pct > 100,
            }
        )
    return heatmap


def compute_project_capacity_summary(project: PrjProject) -> dict[str, Any]:
    """Vue cote projet : liste des membres actifs avec leur allocation +
    total d'allocation COMBINEE sur ce seul projet (peut depasser 100 :
    plusieurs personnes peuvent chacune etre allouees a 100% sur le meme
    projet — seule la somme PAR UTILISATEUR, tous projets confondus, est
    plafonnee par `add_team_member`, jamais la somme des membres d'UN
    projet)."""
    members = PrjTeamMember.objects.filter(project=project, is_active=True)
    member_rows = [
        {
            "member_id": str(member.id),
            "user_id": str(member.user_id),
            "role": member.role,
            "allocation_pct": member.allocation_pct,
        }
        for member in members
    ]
    total_allocation_pct = 0
    for member in members:
        total_allocation_pct += member.allocation_pct
    return {
        "project_id": str(project.id),
        "members": member_rows,
        "total_allocation_pct": total_allocation_pct,
    }
