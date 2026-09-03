"""Registre des gardes d'autorisation objet pour le chatter générique
(`apps.core.views.chatter`) — gap détecté lors de la révision complète
Sprints 0-9 (cf. docs/planning/2026-refonte-ux-sprints.md) : le chatter
n'appliquait jusqu'ici qu'un filtre tenant (via `BaseModel`/RLS), aucune
autorisation par modèle ou par ligne. Seule exposition réelle à ce jour :
`sales/order_detail.html`, sans règle d'accès stricte — mais le composant
est générique et pourrait demain être câblé sur un modèle à accès
restreint (ex. `payroll.PayPayslip`, RG-PAY-9) sans que personne n'ajoute
la garde correspondante.

**Même patron que `core.services.automation_registry`/
`ai_context_registry`** : chaque app enregistre sa propre garde depuis
son `apps.py::ready()`, jamais un import direct de `apps.core` vers cette
app (règle de couplage n°1) — ce module ne connaît AUCUNE app métier.

**Défaut sans garde enregistrée** : `apps.core.views.chatter` retombe sur
`user.has_perm(f"{app_label}.view_{model}")` — même patron déjà établi par
`apps.core.services.search.global_search` pour filtrer les résultats de
recherche par modèle. Un modèle sans garde explicite reste donc couvert
par le système de permissions Django standard (grossier, par modèle),
jamais totalement ouvert."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.core.models.base import BaseModel

ObjectGuard = Callable[["HttpRequest", "BaseModel"], bool]

_GUARDS: dict[tuple[str, str], ObjectGuard] = {}


def register_object_guard(app_label: str, model: str, guard: ObjectGuard) -> None:
    """`guard(request, instance) -> bool` : `True` si `request.user` peut
    voir/poster sur le fil de discussion de `instance`. Enregistrer deux
    fois la même clé (`app_label`, `model`) remplace la garde précédente —
    aucune protection contre un double enregistrement accidentel, comme
    les autres registres partagés de ce dépôt (`automation_registry`,
    `ai_context_registry`)."""
    _GUARDS[(app_label, model.lower())] = guard


def get_object_guard(app_label: str, model: str) -> ObjectGuard | None:
    """`None` si aucune garde n'a été enregistrée pour ce modèle —
    l'appelant (`apps.core.views.chatter`) retombe alors sur
    `user.has_perm`."""
    return _GUARDS.get((app_label, model.lower()))
