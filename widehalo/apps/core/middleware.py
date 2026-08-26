"""Middlewares transversaux du socle.

- TenantMiddleware : resout le tenant courant et active la Row-Level
  Security PostgreSQL pour la duree de la requete (implementation complete
  a l'etape 3).
- MFAEnforcementMiddleware : bloque l'acces applicatif tant qu'un
  utilisateur soumis a MFA obligatoire n'a pas enrole son second facteur
  (implementation complete a l'etape 4).

Doivent s'executer, dans MIDDLEWARE, apres AuthenticationMiddleware (ils
ont besoin de request.user) et avant toute vue/API qui touche l'ORM.
"""

from __future__ import annotations

from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse

from apps.core.context import clear_current_tenant, set_current_tenant


class TenantMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant_id = self._resolve_tenant_id(request)
        set_current_tenant(tenant_id)
        if tenant_id and connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
        try:
            return self.get_response(request)
        finally:
            clear_current_tenant()

    def _resolve_tenant_id(self, request: HttpRequest) -> str | None:
        header_tenant = request.headers.get("X-Tenant-Id")
        if header_tenant:
            return header_tenant
        session_tenant = request.session.get("tenant_id") if hasattr(request, "session") else None
        if session_tenant:
            return str(session_tenant)
        return None


class MFAEnforcementMiddleware:
    """Redirige/bloque les roles soumis a MFA obligatoire sans device confirme.

    Implementation complete a l'etape 4 : pour l'instant, laisse passer
    toutes les requetes (pas de blocage) pour ne pas casser le squelette
    avant que le modele User/roles n'existe.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)
