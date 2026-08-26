"""RBAC N2 (objet-type, via require_permission) et N4 (champ, via
SENSITIVE_FIELDS/filter_fields_for_role). N1 (module) et N3 (enregistrement,
django-guardian) sont geres respectivement par l'appartenance a un groupe
donnant acces a une app et par apply_scope()/assign_perm() au cas par cas
dans les modules metier.

Regle deny-by-default : `require_permission` doit etre applique
explicitement a CHAQUE endpoint django-ninja qui touche des donnees
metier — un endpoint qui l'omet n'est pas "ouvert par erreur", il echoue
(l'utilisateur, meme authentifie, n'a jamais la permission implicite).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.http import JsonResponse

from apps.core.models.user import User

# Registry declaratif des champs sensibles par modele :
# {model_label: {field: {roles autorisees}}}. Exemple d'usage futur (module
# Ventes) : SENSITIVE_FIELDS["sales.SalesOrderLine"] = {"margin": {"direction", "admin"}}
SENSITIVE_FIELDS: dict[str, dict[str, set[str]]] = {}


def require_permission(codename: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorateur pour endpoint django-ninja : renvoie 401 si non
    authentifie, 403 si authentifie mais sans la permission `codename`
    (verifiee via User.has_perm, donc satisfaite par l'appartenance a un
    Group Django porteur de cette permission)."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            user = getattr(request, "auth", None) or getattr(request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                return JsonResponse({"detail": "authentification requise"}, status=401)
            if not user.has_perm(codename):
                return JsonResponse({"detail": "permission refusée"}, status=403)
            return func(request, *args, **kwargs)

        wrapper._required_permission = codename  # type: ignore[attr-defined]
        return wrapper

    return decorator


def user_role_codes(user: User) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def filter_fields_for_role(
    model_label: str, role_codes: set[str], data: dict[str, Any]
) -> dict[str, Any]:
    """Retire du dict de sortie les champs sensibles que les roles de
    l'utilisateur ne sont pas autorises a voir (masquage N4)."""
    sensitive = SENSITIVE_FIELDS.get(model_label, {})
    return {
        key: value
        for key, value in data.items()
        if key not in sensitive or role_codes & sensitive[key]
    }
