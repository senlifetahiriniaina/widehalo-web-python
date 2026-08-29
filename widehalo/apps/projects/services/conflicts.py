"""Resolution automatique des conflits de planification (PJ3) — double
affectation, chevauchements de dates sur un meme `assignee`. Service pur,
AUCUN nouveau modele (differenciateur documente dans le plan : aucun des
quatre concurrents de reference — Asana/Monday/Jira/ClickUp — ne resout
automatiquement ce type de conflit, ils se contentent de l'afficher).

**Perimetre disclosed** : une tache sans `start_date`/`end_date` (les deux
champs sont nullables, cf. `apps/projects/models.py::PrjTask`) ne peut
participer a aucun conflit — elle est simplement ignoree, jamais une
fausse alerte. Une tache `cancelled`/`done` est egalement exclue (un
conflit sur du travail termine ou annule n'a pas de sens metier).

**Politique de resolution automatique — heuristique simple, documentee
comme telle** : entre deux taches en conflit affectees au meme
utilisateur, la tache dont `start_date` est la PLUS TARDIVE (la "seconde"
dans le temps) est decalee pour demarrer le jour ouvrable suivant la fin
de l'autre — sa duree (`duration_days`) est preservee, seule `start_date`/
`end_date` sont deplacees. Ce n'est PAS un optimiseur de planning complet
(pas de reequilibrage global multi-taches, pas de priorisation par
`story_points`/chemin critique) — juste un decalage local suffisant pour
lever le conflit immediat, coherent avec le niveau de sophistication
deja retenu pour `mrp`/`purchase` (jamais une automatisation qui invente
une decision metier complexe sans intervention humaine possible)."""

from __future__ import annotations

import dataclasses
import datetime as dt

from apps.core.models.user import User
from apps.projects.models import PrjTask

_TERMINAL_STATES = {PrjTask.STATE_DONE, PrjTask.STATE_CANCELLED}


@dataclasses.dataclass(frozen=True)
class SchedulingConflict:
    """Paire de taches en conflit (memes affectation + chevauchement de
    dates). `task_a`/`task_b` sont toujours ordonnees par `start_date`
    croissante (`task_a` demarre en premier ou en meme temps)."""

    task_a: PrjTask
    task_b: PrjTask


def _is_schedulable(task: PrjTask) -> bool:
    return (
        task.start_date is not None
        and task.end_date is not None
        and task.state not in _TERMINAL_STATES
    )


def dates_overlap(a_start: dt.date, a_end: dt.date, b_start: dt.date, b_end: dt.date) -> bool:
    """Chevauchement de deux intervalles de dates fermes `[a_start, a_end]`/
    `[b_start, b_end]` — arithmetique pure, reutilisee telle quelle par
    `services/capacity.py::compute_user_workload_heatmap` (PJ7) pour tester
    le chevauchement d'une tache avec une semaine de l'horizon, plutot que
    de dupliquer cette meme comparaison a deux bornes."""
    return a_start <= b_end and b_start <= a_end


def _overlaps(a: PrjTask, b: PrjTask) -> bool:
    assert a.start_date and a.end_date and b.start_date and b.end_date
    return dates_overlap(a.start_date, a.end_date, b.start_date, b.end_date)


def detect_scheduling_conflicts(user: User) -> list[SchedulingConflict]:
    """Detecte tous les chevauchements de dates entre taches actives
    affectees a `user`, tenant courant (RLS deja applique par le manager
    `PrjTask.objects`)."""
    tasks = [
        task
        for task in PrjTask.objects.filter(assignee=user).order_by("start_date", "created_at")
        if _is_schedulable(task)
    ]
    conflicts: list[SchedulingConflict] = []
    for i, task_a in enumerate(tasks):
        for task_b in tasks[i + 1 :]:
            if _overlaps(task_a, task_b):
                conflicts.append(SchedulingConflict(task_a=task_a, task_b=task_b))
    return conflicts


_MAX_RESOLUTION_PASSES = 50


def resolve_conflicts_automatically(user: User) -> list[SchedulingConflict]:
    """Applique la politique de decalage decrite en tete de module,
    conflit par conflit, en RE-DETECTANT apres chaque decalage (un
    decalage peut faire apparaitre un nouveau chevauchement avec une
    troisieme tache — traiter une liste figee des le depart aurait laisse
    ce cas non resolu). Plafonne a `_MAX_RESOLUTION_PASSES` iterations
    pour ne jamais boucler indefiniment sur un cas pathologique (ex.
    plusieurs taches de duree superieure a l'horizon du projet) — au-dela,
    les conflits restants sont laisses tels quels, a traiter manuellement
    (jamais un decalage qui degraderait indefiniment le planning)."""
    resolved: list[SchedulingConflict] = []
    for _ in range(_MAX_RESOLUTION_PASSES):
        conflicts = detect_scheduling_conflicts(user)
        if not conflicts:
            break
        conflict = conflicts[0]
        first, second = conflict.task_a, conflict.task_b
        assert first.end_date and second.duration_days is not None
        new_start = first.end_date + dt.timedelta(days=1)
        new_end = new_start + dt.timedelta(days=max(second.duration_days - 1, 0))
        second.start_date = new_start
        second.end_date = new_end
        second.save(update_fields=["start_date", "end_date"])
        resolved.append(conflict)
    return resolved
