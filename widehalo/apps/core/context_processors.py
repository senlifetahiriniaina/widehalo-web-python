from __future__ import annotations

from django.http import HttpRequest

from apps.core.models.tenant import Tenant
from apps.core.services.permissions import user_role_codes

_ADMIN_ROLE_CODES = {"admin", "direction"}


def tenant(request: HttpRequest) -> dict[str, Tenant | None]:
    """Expose `current_tenant` a tous les templates (footer/header — chantier
    UI signale par l'utilisateur : le nom de la societe doit rester visible
    sur toute page).

    `Tenant.objects` (TenantManager) filtre deja sur le tenant courant via
    la contextvar deja positionnee par `TenantMiddleware` a ce stade du
    cycle de requete (le rendu de template a lieu a l'interieur de la vue,
    donc apres `TenantMiddleware.__call__`) — pas de nouvelle resolution de
    session necessaire ici. Retourne toujours `None` proprement (jamais
    d'exception) pour un visiteur anonyme ou avant creation de la premiere
    societe."""
    return {"current_tenant": Tenant.objects.first()}


def account(request: HttpRequest) -> dict[str, bool]:
    """Expose `is_admin_user` a tous les templates (chantier menu compte
    utilisateur / section Administration signale par l'utilisateur) —
    permet a `base.html` de conditionner l'affichage de la section
    Administration (gatee admin/direction/superutilisateur) sans dupliquer
    ce calcul dans chaque vue.

    Meme idiome que le reste du depot pour verifier un role depuis du HTML
    classique (`user_role_codes(user) & {...}`, deja utilise par
    `apps/payroll/views.py`/`apps/sales/views.py`/`apps/ai/views.py`) —
    jamais `require_permission()` (django-ninja uniquement). Retourne
    toujours `False` proprement (jamais d'exception) pour un visiteur
    anonyme."""
    user = request.user
    if not user.is_authenticated:
        return {"is_admin_user": False}
    is_admin = bool(user_role_codes(user) & _ADMIN_ROLE_CODES) or user.is_superuser
    return {"is_admin_user": is_admin}
