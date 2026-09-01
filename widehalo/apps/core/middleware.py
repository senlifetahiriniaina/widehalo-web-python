"""Middlewares transversaux du socle.

- TenantMiddleware : resout le tenant courant et active la Row-Level
  Security PostgreSQL pour la duree de la requete (implementation complete
  a l'etape 3).
- OnboardingMiddleware : force, dans l'ordre, le changement du mot de passe
  temporaire du compte admin par defaut puis le parametrage de la premiere
  societe de l'instance, avant tout acces web (session) — cf.
  `apps.core.management.commands.bootstrap_admin`.
- MFAEnforcementMiddleware : bloque l'acces applicatif tant qu'un
  utilisateur soumis a MFA obligatoire n'a pas enrole son second facteur
  (implementation complete a l'etape 4).

Doivent s'executer, dans MIDDLEWARE, apres AuthenticationMiddleware (ils
ont besoin de request.user) et avant toute vue/API qui touche l'ORM.
"""

from __future__ import annotations

from collections.abc import Callable

from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse

from apps.core.context import clear_current_tenant, set_current_tenant


class TenantMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant_id = self._resolve_tenant_id(request)
        set_current_tenant(tenant_id)
        try:
            if tenant_id and connection.vendor == "postgresql":
                # `SET LOCAL` ne tient que pour la transaction en cours : sans
                # ATOMIC_REQUESTS, chaque requete SQL serait sinon sa propre
                # transaction implicite et perdrait le reglage avant la
                # prochaine requete (cf. apps/core/tenant_context.py). On
                # englobe donc toute la vue dans un bloc atomique explicite.
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
                    return self.get_response(request)
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


ONBOARDING_EXEMPT_PATH_PREFIXES = (
    "/api/",
    "/admin/",
    "/static/",
    "/media/",
    "/login/",
    "/logout/",
    "/change-password/",
    "/setup/",
    "/__debug__/",
    # UXR1 : lien de confirmation d'e-mail (`confirm_email_view`, vue
    # PUBLIQUE) — le destinataire peut cliquer depuis sa boite mail avec
    # une session existante mais incomplete (mot de passe temporaire pas
    # encore change, aucune societe encore parametree) ; cette page doit
    # rester atteignable dans tous les cas, meme discipline que les 2
    # exemptions ci-dessus.
    "/account/",
)


class OnboardingMiddleware:
    """Bloque l'acces web (session, jamais l'API) tant que l'utilisateur
    authentifie n'a pas, DANS CET ORDRE : (1) change son mot de passe
    temporaire (`must_change_password`, pose par `bootstrap_admin`), (2)
    parametre la premiere societe de l'instance si aucune n'existe encore
    (`Tenant.objects.exists()` — un controle global a l'instance, jamais par
    utilisateur : ne redirige donc jamais un utilisateur normal d'une
    instance deja parametree, meme s'il n'a lui-meme aucune societe).

    Volontairement AVANT MFAEnforcementMiddleware dans MIDDLEWARE : changer
    un mot de passe partage connu avant d'enroler un second facteur dessus,
    jamais l'inverse."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(ONBOARDING_EXEMPT_PATH_PREFIXES):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            from django.shortcuts import redirect

            if getattr(user, "must_change_password", False):
                return redirect("change_password")

            from apps.core.models.tenant import Tenant

            if not Tenant.objects.exists():
                return redirect("setup_company")

        return self.get_response(request)


EXEMPT_PATH_PREFIXES = (
    "/api/",
    "/admin/",
    "/static/",
    "/media/",
    "/mfa/",
    "/login/",
    # Sans ces deux exemptions, un compte soumis a MFA obligatoire (dont le
    # compte admin par defaut, is_superuser=True) ne peut JAMAIS atteindre
    # ces deux ecrans d'amorçage (OnboardingMiddleware, execute juste avant
    # ce middleware dans MIDDLEWARE) — bloque en boucle vers /mfa/ avant
    # meme d'avoir pu changer son mot de passe ou creer la premiere societe.
    # Bug reel trouve par les tests de apps/core/tests/test_onboarding.py.
    "/change-password/",
    "/setup/",
    "/__debug__/",
    "/account/",  # UXR1 : meme raison que dans ONBOARDING_EXEMPT_PATH_PREFIXES.
)


class MFAEnforcementMiddleware:
    """Bloque l'acces web (session, pas API — l'API gate la MFA a la
    connexion, cf. apps/core/services/auth.py) pour un utilisateur soumis a
    MFA obligatoire tant que la session n'est pas verifiee OTP
    (request.user.is_verified(), pose par django_otp.middleware.OTPMiddleware
    en amont dans MIDDLEWARE).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(EXEMPT_PATH_PREFIXES):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            from apps.core.services.mfa import mfa_required_for_user

            is_verified = getattr(user, "is_verified", lambda: True)()
            if mfa_required_for_user(user) and not is_verified:
                from django.shortcuts import redirect

                return redirect("/mfa/")

        return self.get_response(request)
