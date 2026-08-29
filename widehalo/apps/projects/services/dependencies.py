"""Dependances entre taches (PJ2) — detection de cycle a la creation.

Differenciateur documente au plan (§ Module `projects`) comme absent des
outils de reference (Asana/Monday/Jira/ClickUp) : ce module refuse
EXPLICITEMENT (leve `ValidationError`, jamais une creation silencieuse
suivie d'un crash ailleurs, ex. dans le calcul CPM de `services/gantt.py`)
toute dependance qui introduirait un cycle dans le graphe des dependances
du projet. Deux formes de cycle testees explicitement (cf.
`tests/test_dependencies.py`) :
- cycle direct : A -> B puis B -> A ;
- cycle indirect : A -> B -> C puis C -> A.

Algorithme : parcours en profondeur (DFS) classique. Ajouter l'arete
`from_task -> to_task` fermerait un cycle si et seulement si `from_task`
est deja atteignable depuis `to_task` en suivant les dependances
EXISTANTES du projet (`to_task -> ... -> from_task`) — auquel cas la
nouvelle arete refermerait la boucle. Complexite O(V+E) par appel, tout a
fait suffisant pour la taille d'un graphe de taches projet."""

from __future__ import annotations

from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.projects.models import PrjTask, PrjTaskDependency


def _creates_cycle(from_task_id: UUID, to_task_id: UUID) -> bool:
    """DFS depuis `to_task_id` dans le graphe EXISTANT (colonnes
    `from_task_id -> to_task_id` de `PrjTaskDependency`) : si `from_task_id`
    est atteignable, l'arete proposee `from_task_id -> to_task_id`
    fermerait un cycle."""
    visited: set[UUID] = set()
    stack: list[UUID] = [to_task_id]
    while stack:
        current = stack.pop()
        if current == from_task_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        next_ids = list(
            PrjTaskDependency.objects.filter(from_task_id=current, is_active=True).values_list(
                "to_task_id", flat=True
            )
        )
        stack.extend(next_ids)
    return False


def add_dependency(
    from_task: PrjTask,
    to_task: PrjTask,
    dependency_type: str = PrjTaskDependency.TYPE_FINISH_TO_START,
) -> PrjTaskDependency:
    """Cree une `PrjTaskDependency` `from_task -> to_task`, ou leve
    `ValidationError` si la dependance est invalide : auto-dependance,
    taches de projets differents, doublon, ou cycle (direct/indirect)."""
    if from_task.id == to_task.id:
        raise ValidationError(_("Une tache ne peut pas dependre d'elle-meme."))
    if from_task.project_id != to_task.project_id:
        raise ValidationError(
            _("Les deux taches d'une dependance doivent appartenir au meme projet.")
        )
    if PrjTaskDependency.objects.filter(
        from_task=from_task, to_task=to_task, is_active=True
    ).exists():
        raise ValidationError(_("Cette dependance existe deja."))
    if _creates_cycle(from_task.id, to_task.id):
        raise ValidationError(
            _("Cette dependance introduirait un cycle dans le graphe de dependances du projet.")
        )
    return PrjTaskDependency.objects.create(
        tenant=from_task.tenant,
        from_task=from_task,
        to_task=to_task,
        dependency_type=dependency_type,
    )
