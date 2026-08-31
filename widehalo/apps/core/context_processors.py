from __future__ import annotations

from django.http import HttpRequest

from apps.core.models.tenant import Tenant


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
