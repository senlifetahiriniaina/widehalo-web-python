"""Logique de connexion : authentification + verrouillage (django-axes,
branche via AUTHENTICATION_BACKENDS) + gating MFA pour les roles sensibles.
Emission des tokens JWT deleguee a ninja_jwt (access 15 min / refresh 7 j,
revocable via ninja_jwt.token_blacklist)."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import authenticate
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
    user = authenticate(request, username=email, password=password)
    if user is None:
        return LoginResult(status="invalid_credentials")

    if mfa_required_for_user(user):
        if not has_confirmed_device(user):
            return LoginResult(status="mfa_enrollment_required", user=user)
        return LoginResult(status="mfa_required", user=user)

    access, refresh = issue_tokens(user)
    return LoginResult(status="ok", user=user, access=access, refresh=refresh)


def complete_mfa_login(user: User) -> LoginResult:
    access, refresh = issue_tokens(user)
    return LoginResult(status="ok", user=user, access=access, refresh=refresh)
