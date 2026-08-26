"""Portee (scoping) RBAC de niveau N3, centralisee : tout module metier
futur restreint ses querysets via `apply_scope()` plutot que d'implementer
sa propre logique de filtrage par role.

Les scopes `entity/team/workshop/warehouse` dependent de modeles qui
n'existent pas encore dans ce lot (Team, Workshop, Warehouse seront definis
par de futurs modules metier) — ils restent des hooks fonctionnels
(retournent le queryset filtre sur `global` par defaut) : dette anticipee
assumee, documentee dans le plan.
"""

from __future__ import annotations

from typing import Literal, TypeVar

from django.db.models import Model, QuerySet

from apps.core.models.user import User

Scope = Literal["global", "entity", "team", "workshop", "warehouse", "own"]

M = TypeVar("M", bound=Model)


def apply_scope(queryset: QuerySet[M], user: User, scope: Scope) -> QuerySet[M]:  # noqa: UP047
    if scope == "own":
        return queryset.filter(created_by=user)
    if scope == "global":
        return queryset
    # entity/team/workshop/warehouse : hooks non enrichis dans ce lot socle
    # (aucun modele Team/Workshop/Warehouse existant), traites comme
    # "global" en attendant les modules metier qui les definiront.
    return queryset
