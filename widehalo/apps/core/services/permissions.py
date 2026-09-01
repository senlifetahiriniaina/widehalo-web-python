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
from django.utils.translation import gettext as _

from apps.core.models.user import User

# Registry declaratif des champs sensibles par modele :
# {model_label: {field: {roles autorisees}}}. Exemple d'usage futur (module
# Ventes) : SENSITIVE_FIELDS["sales.SalesOrderLine"] = {"margin": {"direction", "admin"}}
SENSITIVE_FIELDS: dict[str, dict[str, set[str]]] = {}

# RG-SAL-5 (§5.5, S7) : premiere population reelle de ce registre, jamais
# utilise par aucun module avant `sales`. Le champ reel s'appelle
# `margin_pct` (pas "margin", cf. `apps.sales.models.SalesOrderLine`/
# `SalesQuotationLine`). Roles autorises a voir la marge : `direction`/
# `admin` (pilotage transverse) et `resp_commercial` (responsable
# commercial, doit pouvoir arbitrer une remise en connaissance de cause) —
# EXCLUS explicitement : `commercial` (un commercial ne doit pas voir la
# marge sur les lignes qu'il chiffre au client, seulement le prix). Choix
# aligne sur `apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS["sales"]`
# (S1) qui donne acces au module `sales` a exactement ces 4 roles
# (`admin`/`direction`/`commercial`/`resp_commercial`) — `margin_pct` est
# donc masque au seul role qui, parmi les 4, n'a pas de responsabilite de
# pilotage/marge. Applique aux DEUX modeles qui portent le champ (devis ET
# commande) : le CDC ne mentionne que "sales.SalesOrderLine" dans son
# commentaire d'exemple, mais `SalesQuotationLine.margin_pct` porte la
# meme information sensible et doit etre masque de la meme facon.
# `cost_estimate_mga` (cout de revient estime) est ajoute au meme role-set :
# un cout de revient permet de reconstituer la marge par simple soustraction
# du prix de vente (deja visible de tout `commercial`) — le masquer
# seulement partiellement (marge oui, cout non) aurait laisse une fuite
# triviale de la meme information sensible.
_MARGIN_VISIBLE_ROLES = {"direction", "admin", "resp_commercial"}
SENSITIVE_FIELDS["sales.SalesOrderLine"] = {
    "margin_pct": set(_MARGIN_VISIBLE_ROLES),
    "cost_estimate_mga": set(_MARGIN_VISIBLE_ROLES),
}
SENSITIVE_FIELDS["sales.SalesQuotationLine"] = {
    "margin_pct": set(_MARGIN_VISIBLE_ROLES),
    "cost_estimate_mga": set(_MARGIN_VISIBLE_ROLES),
}

# RG-PAY-9 (§5.10.6, chantier `payroll`, stricte) : "managers ne voient
# AUCUN montant" — `resp_production`/`chef_atelier`/`resp_commercial`
# recoivent "view" sur le module `payroll` (cf.
# `rbac_policy.ROLE_APP_PERMISSIONS`, acces a l'existence/l'etat d'un
# bulletin) mais AUCUN de ces 3 roles n'apparait dans `_PAYROLL_AMOUNT_
# VISIBLE_ROLES` ci-dessous : tout champ monetaire de `PayPayslip`/
# `PayPayslipLine` leur reste masque. `collaborateur` (scope "own", ses
# propres bulletins uniquement) EST inclus : un employe doit voir SES
# PROPRES montants, seul le regard d'un manager sur l'equipe est concerne
# par la restriction du CDC.
_PAYROLL_AMOUNT_VISIBLE_ROLES = {"rh", "direction", "admin", "collaborateur"}
_PAYROLL_PAYSLIP_AMOUNT_FIELDS = {
    "gross",
    "taxable_base",
    "irsa",
    "social_employee",
    "social_employer",
    "net_to_pay",
}
SENSITIVE_FIELDS["payroll.PayPayslip"] = {
    field: set(_PAYROLL_AMOUNT_VISIBLE_ROLES) for field in _PAYROLL_PAYSLIP_AMOUNT_FIELDS
}
SENSITIVE_FIELDS["payroll.PayPayslipLine"] = {
    "base": set(_PAYROLL_AMOUNT_VISIBLE_ROLES),
    "rate": set(_PAYROLL_AMOUNT_VISIBLE_ROLES),
    "amount": set(_PAYROLL_AMOUNT_VISIBLE_ROLES),
}


class _PermissionGuardedView:
    """Objet appelable (plutot qu'une fermeture `def wrapper(...)`) qui
    porte le controle de permission de `require_permission`.

    Pourquoi un objet et pas une fermeture : cote routage, django-ninja
    doit reconstruire le type des parametres annotes par une chaine (a
    cause de `from __future__ import annotations` dans les modules
    `apps/*/api.py`) via `ninja.signature.utils.get_typed_signature`, qui
    resout ces annotations avec `getattr(call, "__globals__", {})` — SANS
    remonter la chaine `__wrapped__` (contrairement a
    `inspect.signature`/`typing.get_type_hints`, qui eux la suivent).
    Une fermeture Python a un `__globals__` fige sur le module ou elle est
    *definie* (ici `apps.core.services.permissions`), meme apres
    `functools.wraps` : celui-ci copie `__name__`/`__module module__`/
    `__doc__`/`__dict__`/`__wrapped__` mais ne peut PAS reaffecter
    `__globals__` (attribut natif en lecture seule d'un objet fonction).
    Consequence concrete observee : tout endpoint POST/PATCH dont le
    payload est un `Schema` (ex. `InvoiceIn`) etait alors mal classifie
    par ninja (ForwardRef non resolue -> traite comme parametre de query
    au lieu du corps -> 500 pour tout appelant, meme autorise).

    Un objet appelable expose `__globals__` via `__getattr__` en le
    delegant a la fonction d'origine (`self._func.__globals__`), ce qui
    satisfait `getattr(call, "__globals__", {})` avec le bon namespace
    (celui du module ou vit reellement la vue, ex. `apps.accounting.api`)
    tout en laissant `inspect.signature`/`typing.get_type_hints` suivre
    `__wrapped__` comme avant. Pas de dependance supplementaire (type
    `wrapt`) requise."""

    def __init__(self, func: Callable[..., Any], codename: str) -> None:
        functools.update_wrapper(self, func)
        self._func = func
        self._codename = codename
        self._required_permission = codename

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        user = getattr(request, "auth", None) or getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return JsonResponse({"detail": _("authentification requise")}, status=401)
        if not user.has_perm(self._codename):
            return JsonResponse({"detail": _("permission refusée")}, status=403)
        return self._func(request, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Uniquement pour les attributs absents de `self.__dict__` (ex.
        # `__globals__`, jamais copie par `functools.update_wrapper`) :
        # delegue a la fonction d'origine plutot que de lever AttributeError.
        return getattr(self._func, name)


def require_permission(codename: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorateur pour endpoint django-ninja : renvoie 401 si non
    authentifie, 403 si authentifie mais sans la permission `codename`
    (verifiee via User.has_perm, donc satisfaite par l'appartenance a un
    Group Django porteur de cette permission).

    IMPORTANT (ordre des decorateurs) : `@router.get/post/...` DOIT rester
    le decorateur EXTERNE et `@require_permission(...)` l'INTERNE (juste
    au-dessus de `def`) — `Router.api_operation` enregistre dans sa table
    de routage la fonction qui lui est passee directement, puis la
    retourne INCHANGEE ; place a l'exterieur, `require_permission`
    n'intercepterait donc plus jamais aucune requete HTTP reelle (verifie
    empiriquement)."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return _PermissionGuardedView(func, codename)

    return decorator


class _SuperuserGuardedView:
    """Meme mecanisme (et meme raison d'etre, cf. docstring de
    `_PermissionGuardedView`) que le garde de permission ci-dessus, mais
    reserve au SUPERADMINISTRATEUR uniquement (`request.user.is_superuser`)
    — jamais une permission Django/RBAC generique, qui n'attribue de
    droits qu'a des GROUPES et laisserait donc passer `admin`/`direction`
    des qu'un groupe la porte. A utiliser pour les operations qui doivent
    rester hors de portee de TOUT role, meme de pilotage transverse (ex.
    sauvegarde/restauration/reinitialisation d'un tenant, cf.
    `apps.core.api_backup`)."""

    def __init__(self, func: Callable[..., Any]) -> None:
        functools.update_wrapper(self, func)
        self._func = func

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        user = getattr(request, "auth", None) or getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return JsonResponse({"detail": _("authentification requise")}, status=401)
        if not getattr(user, "is_superuser", False):
            return JsonResponse({"detail": _("réservé au superadministrateur")}, status=403)
        return self._func(request, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._func, name)


def require_superuser(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorateur pour endpoint django-ninja : renvoie 401 si non
    authentifie, 403 si authentifie mais `is_superuser` est faux — jamais
    satisfait par une permission/role RBAC, meme `admin`/`direction`.
    Meme regle d'ordre de decorateurs que `require_permission` (cf. sa
    docstring) : `@router.get/post/...` reste l'exterieur,
    `@require_superuser` l'interieur, juste au-dessus de `def`. Pas
    d'argument (contrairement a `require_permission(codename)`) : usage
    direct `@require_superuser`."""
    return _SuperuserGuardedView(func)


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
