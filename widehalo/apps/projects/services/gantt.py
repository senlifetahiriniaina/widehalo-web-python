"""Service Gantt (PJ2) : calcul du chemin critique (CPM) et rendu SVG
serveur du diagramme de Gantt — cf. plan, section « Module `projects` »,
etape PJ2.

**Hypotheses simplificatrices V1, disclosed explicitement** (meme
discipline que le reste de ce projet — une simplification documentee
plutot qu'une fausse precision) :
1. **Jours calendaires simples** : aucun calendrier ouvre (jours feries,
   week-ends non travailles) n'est modelise en V1 — un jour = 24h, tous
   les jours comptent. Un futur calendrier ouvre par tenant est un
   candidat naturel d'evolution (hors perimetre PJ2).
2. **Toute dependance est traitee comme `finish_to_start` pour le calcul
   CPM lui-meme** : `PrjTaskDependency.dependency_type` est bien
   stocke/affiche (fleches du Gantt, cf. `render_gantt_svg`), mais le
   forward/backward pass mathematique de `compute_critical_path`
   applique uniformement la semantique "la tache aval ne peut demarrer
   qu'apres la fin de la tache amont" — la prise en compte mathematique
   complete des 3 autres types (start_to_start/finish_to_finish/
   start_to_finish) est reportee a un chantier ulterieur.
3. **Duree d'une tache** : `duration_days` si renseigne (>0), sinon
   `(end_date - start_date).days` si les deux dates sont renseignees,
   sinon 0 (tache instantanee, typiquement un jalon).
4. **Ancrage temporel des taches sans predecesseur** : leur `start_date`
   planifiee si renseignee, sinon l'epoque du projet (date la plus
   ancienne parmi les `start_date` deja renseignees du projet, ou la
   date du jour si aucune tache n'a de date).
5. **Chemin critique = marge (slack) nulle** (`latest_start - earliest_
   start == 0 jour`), definition CPM standard.

`render_gantt_svg` est une PROJECTION SVG simple des donnees (largeur des
barres proportionnelle a la duree, position selon `start_date`, fleches de
dependance, couleur distincte pour le chemin critique) — **pas un moteur
de rendu Gantt complet** : pas de zoom, echelle fixe (`_DAY_WIDTH` px par
jour calendaire), pas de tri interactif des lignes. L'interactivite
(deplacement des dates) vient de l'endpoint `PATCH
/api/v1/projects/tasks/{id}/gantt` (cf. `apps/projects/api.py`), pas de ce
rendu SVG lui-meme — coherent avec le renouvellement recent de l'UI de ce
projet (htmx/Alpine, pas de librairie JS de Gantt tierce)."""

from __future__ import annotations

import datetime as dt
from html import escape
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.projects.models import PrjProject, PrjTask, PrjTaskDependency

_DAY_WIDTH = 24
_ROW_HEIGHT = 32
_LEFT_MARGIN = 180
_TOP_MARGIN = 40
_BAR_HEIGHT = 18
_COLOR_NORMAL = "#4c6ef5"
_COLOR_CRITICAL = "#e8590c"
_COLOR_ARROW = "#868e96"


def _task_duration_days(task: PrjTask) -> int:
    if task.duration_days:
        return task.duration_days
    if task.start_date and task.end_date:
        return max((task.end_date - task.start_date).days, 0)
    return 0


def _topological_order(task_ids: list[UUID], predecessors: dict[UUID, list[UUID]]) -> list[UUID]:
    """Tri topologique de Kahn. En pratique le graphe est toujours acyclique
    (garanti par `services.dependencies.add_dependency` a la creation) ;
    la detection de cycle ici reste un garde-fou defensif (ex. donnees
    injectees hors service, migration de donnees) plutot qu'un chemin
    normalement emprunte."""
    successors: dict[UUID, list[UUID]] = {tid: [] for tid in task_ids}
    for tid, preds in predecessors.items():
        for pred in preds:
            successors[pred].append(tid)
    in_degree = {tid: len(predecessors[tid]) for tid in task_ids}
    queue = [tid for tid in task_ids if in_degree[tid] == 0]
    order: list[UUID] = []
    while queue:
        node = queue.pop()
        order.append(node)
        for succ in successors[node]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)
    if len(order) != len(task_ids):
        raise ValidationError(
            _("Cycle detecte dans le graphe de dependances du projet — calcul CPM impossible.")
        )
    return order


def compute_critical_path(project: PrjProject) -> set[UUID]:
    """Algorithme CPM (Critical Path Method) classique : forward pass
    (dates au plus tot) puis backward pass (dates au plus tard), a partir
    de `start_date`/`end_date`/`duration_days` de chaque `PrjTask` actif du
    projet et du graphe `PrjTaskDependency`. Met a jour `is_critical_path`
    pour CHAQUE tache du projet (`True` si marge nulle, `False` sinon) et
    renvoie l'ensemble des UUID des taches sur le chemin critique. Cf.
    docstring de module pour les hypotheses simplificatrices retenues."""
    tasks = list(project.tasks.filter(is_active=True))
    if not tasks:
        return set()

    tasks_by_id = {t.id: t for t in tasks}
    task_ids = list(tasks_by_id.keys())

    deps = PrjTaskDependency.objects.filter(
        from_task__in=task_ids, to_task__in=task_ids, is_active=True
    ).values_list("from_task_id", "to_task_id")
    predecessors: dict[UUID, list[UUID]] = {tid: [] for tid in task_ids}
    for from_id, to_id in deps:
        predecessors[to_id].append(from_id)

    order = _topological_order(task_ids, predecessors)

    epoch = min((t.start_date for t in tasks if t.start_date), default=dt.date.today())

    earliest_start: dict[UUID, dt.date] = {}
    earliest_finish: dict[UUID, dt.date] = {}
    for task_id in order:
        task = tasks_by_id[task_id]
        preds = predecessors[task_id]
        start = max((earliest_finish[p] for p in preds), default=task.start_date or epoch)
        earliest_start[task_id] = start
        earliest_finish[task_id] = start + dt.timedelta(days=_task_duration_days(task))

    project_finish = max(earliest_finish.values())

    successors: dict[UUID, list[UUID]] = {tid: [] for tid in task_ids}
    for from_id, to_id in deps:
        successors[from_id].append(to_id)

    latest_start: dict[UUID, dt.date] = {}
    latest_finish: dict[UUID, dt.date] = {}
    for task_id in reversed(order):
        task = tasks_by_id[task_id]
        succs = successors[task_id]
        finish = min((latest_start[s] for s in succs), default=project_finish)
        latest_finish[task_id] = finish
        latest_start[task_id] = finish - dt.timedelta(days=_task_duration_days(task))

    critical_ids = {
        task_id
        for task_id in task_ids
        if (latest_start[task_id] - earliest_start[task_id]).days == 0
    }

    PrjTask.objects.filter(id__in=task_ids).update(is_critical_path=False)
    if critical_ids:
        PrjTask.objects.filter(id__in=critical_ids).update(is_critical_path=True)

    return critical_ids


def render_gantt_svg(project: PrjProject) -> str:
    """Rendu SVG serveur du Gantt du projet — cf. docstring de module pour
    les limitations explicitement assumees (pas de librairie JS tierce,
    echelle fixe, pas d'interactivite dans ce rendu)."""
    tasks = list(project.tasks.filter(is_active=True).order_by("start_date", "created_at"))
    if not tasks:
        message = escape(str(_("Aucune tache a planifier.")))
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="60" '
            'class="gantt-empty">'
            f'<text x="10" y="30">{message}</text>'
            "</svg>"
        )

    epoch = min((t.start_date for t in tasks if t.start_date), default=dt.date.today())

    def _bounds(task: PrjTask) -> tuple[dt.date, dt.date]:
        start = task.start_date or epoch
        if task.end_date and task.end_date > start:
            end = task.end_date
        else:
            end = start + dt.timedelta(days=max(task.duration_days, 1))
        return start, end

    bounds = {t.id: _bounds(t) for t in tasks}
    min_date = min(s for s, _end in bounds.values())
    max_date = max(e for _start, e in bounds.values())
    total_days = max((max_date - min_date).days, 1)

    width = _LEFT_MARGIN + total_days * _DAY_WIDTH + 40
    height = _TOP_MARGIN + len(tasks) * _ROW_HEIGHT + 20
    row_index = {t.id: i for i, t in enumerate(tasks)}

    def _x(date: dt.date) -> float:
        return _LEFT_MARGIN + (date - min_date).days * _DAY_WIDTH

    def _y(index: int) -> float:
        return _TOP_MARGIN + index * _ROW_HEIGHT

    title = escape(str(_("Diagramme de Gantt")))
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title}" class="gantt-svg">',
        (
            '<defs><marker id="gantt-arrow" markerWidth="8" markerHeight="8" refX="6" '
            f'refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="{_COLOR_ARROW}" />'
            "</marker></defs>"
        ),
    ]

    for task in tasks:
        idx = row_index[task.id]
        start, end = bounds[task.id]
        x = _x(start)
        y = _y(idx)
        bar_width = max((end - start).days * _DAY_WIDTH, 4)
        css_class = "gantt-task gantt-task-critical" if task.is_critical_path else "gantt-task"
        color = _COLOR_CRITICAL if task.is_critical_path else _COLOR_NORMAL
        label = escape(task.reference or str(task.id))
        task_name = escape(task.get_task_type_display())
        text_y = y + _BAR_HEIGHT - 4
        parts.append(f'<text x="4" y="{text_y}" class="gantt-row-label">{label}</text>')
        parts.append(
            f'<rect class="{css_class}" x="{x}" y="{y}" width="{bar_width}" '
            f'height="{_BAR_HEIGHT}" fill="{color}" data-task-id="{task.id}">'
            f"<title>{task_name}</title></rect>"
        )

    deps = PrjTaskDependency.objects.filter(from_task__in=tasks, to_task__in=tasks, is_active=True)
    for dep in deps:
        if dep.from_task_id not in row_index or dep.to_task_id not in row_index:
            continue
        _from_start, from_end = bounds[dep.from_task_id]
        to_start, _to_end = bounds[dep.to_task_id]
        x1 = _x(from_end)
        y1 = _y(row_index[dep.from_task_id]) + _BAR_HEIGHT / 2
        x2 = _x(to_start)
        y2 = _y(row_index[dep.to_task_id]) + _BAR_HEIGHT / 2
        parts.append(
            f'<line class="gantt-dependency" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{_COLOR_ARROW}" stroke-width="1.5" marker-end="url(#gantt-arrow)" />'
        )

    parts.append("</svg>")
    return "".join(parts)
