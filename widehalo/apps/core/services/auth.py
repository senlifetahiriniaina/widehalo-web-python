"""Logique de connexion : authentification + verrouillage (django-axes,
branche via AUTHENTICATION_BACKENDS) + gating MFA pour les roles sensibles.
Emission des tokens JWT deleguee a ninja_jwt (access 15 min / refresh 7 j,
revocable via ninja_jwt.token_blacklist)."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import authenticate
from django.contrib.auth.signals import user_logged_in
from django.http import HttpRequest
from ninja_jwt.tokens import RefreshToken

from apps.core.models.user import User
from apps.core.services.mfa import has_confirmed_device, mfa_required_for_user


@dataclass
class LoginResult:
    status: str
    user: User | None = None
    access: str | None = None
    refresh: str | None = None


def issue_tokens(user: User) -> tuple[str, str]:
    refresh = RefreshToken.for_user(user)  # type: ignore[misc]  # bug de stub ninja_jwt
    return str(refresh.access_token), str(refresh)


def login(request: HttpRequest, email: str, password: str) -> LoginResult:
    # `authenticate()` envoie lui-meme le signal standard Django
    # `user_login_failed` (credentials invalides) — deja ecoute par
    # django-axes ET, depuis ce correctif, par
    # `apps.core.audit_signals` (ACTION_LOGIN_FAILED, cahier §6.5).
    user = authenticate(request, username=email, password=password)
    if user is None:
        return LoginResult(status="invalid_credentials")

    if mfa_required_for_user(user):
        if not has_confirmed_device(user):
            return LoginResult(status="mfa_enrollment_required", user=user)
        return LoginResult(status="mfa_required", user=user)

    access, refresh = issue_tokens(user)
    # Ce flux JWT n'appelle jamais `django.contrib.auth.login()` (pas de
    # session a etablir) donc le signal standard `user_logged_in` ne
    # partirait jamais tout seul ici, contrairement au flux session
    # `apps.core.views.auth_web.login_view` — envoye explicitement pour que
    # les DEUX flux alimentent le meme point d'ecoute unique
    # (`apps.core.audit_signals`), sans dupliquer la logique de
    # journalisation dans chaque vue/endpoint de connexion.
    user_logged_in.send(sender=user.__class__, request=request, user=user)
    return LoginResult(status="ok", user=user, access=access, refresh=refresh)


def complete_mfa_login(request: HttpRequest, user: User) -> LoginResult:
    access, refresh = issue_tokens(user)
    user_logged_in.send(sender=user.__class__, request=request, user=user)
    return LoginResult(status="ok", user=user, access=access, refresh=refresh)
