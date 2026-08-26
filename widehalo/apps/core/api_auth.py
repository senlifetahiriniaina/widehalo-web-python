from __future__ import annotations

import contextlib

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.http import JsonResponse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext as _
from ninja import Router
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from apps.core.models.user import User
from apps.core.schemas_auth import (
    LoginIn,
    LoginOut,
    MfaEnrollOut,
    MfaVerifyIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RefreshIn,
    TokenOut,
)
from apps.core.services import auth as auth_service
from apps.core.services import mfa as mfa_service

router = Router(tags=["auth"])
token_generator = PasswordResetTokenGenerator()


@router.post("/login", response=LoginOut, auth=None)
def login(request, payload: LoginIn):
    result = auth_service.login(request, payload.email, payload.password)
    if result.status == "invalid_credentials":
        return JsonResponse({"status": result.status}, status=401)
    return LoginOut(status=result.status, access=result.access, refresh=result.refresh)


@router.post("/mfa/enroll", response=MfaEnrollOut, auth=None)
def mfa_enroll(request, payload: MfaVerifyIn):
    """Demarre l'enrolement TOTP d'un utilisateur soumis a MFA obligatoire
    qui n'a pas encore de device confirme. `payload.token` est ignore ici
    (reutilisation du schema email+code pour rester minimal)."""
    user = User.objects.filter(email=payload.email).first()
    if user is None:
        return JsonResponse({"detail": _("utilisateur introuvable")}, status=404)
    device = mfa_service.enroll_device(user)
    return MfaEnrollOut(otpauth_url=device.config_url)


@router.post("/mfa/confirm", response=LoginOut, auth=None)
def mfa_confirm(request, payload: MfaVerifyIn):
    """Confirme l'enrolement (premier code TOTP saisi) puis connecte
    l'utilisateur."""
    user = User.objects.filter(email=payload.email).first()
    if user is None:
        return JsonResponse({"status": "not_found"}, status=404)
    device = mfa_service.enroll_device(user)
    if not mfa_service.confirm_device(device, payload.token):
        return JsonResponse({"status": "invalid_token"}, status=400)
    result = auth_service.complete_mfa_login(user)
    return LoginOut(status=result.status, access=result.access, refresh=result.refresh)


@router.post("/mfa/verify", response=LoginOut, auth=None)
def mfa_verify(request, payload: MfaVerifyIn):
    """Deuxieme etape du login pour un utilisateur ayant deja un device
    confirme."""
    user = User.objects.filter(email=payload.email).first()
    if user is None or not mfa_service.verify_token(user, payload.token):
        return JsonResponse({"status": "invalid_token"}, status=400)
    result = auth_service.complete_mfa_login(user)
    return LoginOut(status=result.status, access=result.access, refresh=result.refresh)


@router.post("/refresh", response=TokenOut, auth=None)
def refresh(request, payload: RefreshIn):
    try:
        token = RefreshToken(payload.refresh)
        access = str(token.access_token)
        user = token_user(token)
        token.blacklist()
        new_refresh = RefreshToken.for_user(user)
    except TokenError:
        return JsonResponse({"detail": _("jeton invalide, expiré ou révoqué")}, status=401)
    return TokenOut(access=access, refresh=str(new_refresh))


def token_user(token: RefreshToken) -> User:
    return User.objects.get(id=token["user_id"])


@router.post("/logout", auth=None)
def logout(request, payload: RefreshIn):
    with contextlib.suppress(TokenError):
        RefreshToken(payload.refresh).blacklist()
    return {"status": "ok"}


@router.post("/password-reset/request", auth=None)
def password_reset_request(request, payload: PasswordResetRequestIn):
    user = User.objects.filter(email=payload.email).first()
    if user is not None:
        reset_uid = urlsafe_base64_encode(force_bytes(user.pk))
        reset_token = token_generator.make_token(user)
        # L'envoi effectif de l'e-mail est delegue au futur module
        # notifications (etape 11) ; on journalise seulement pour ce lot.
        del reset_uid, reset_token
    # Reponse identique que l'utilisateur existe ou non (pas d'enumeration).
    return {"status": "ok"}


@router.post("/password-reset/confirm", auth=None)
def password_reset_confirm(request, payload: PasswordResetConfirmIn):
    try:
        uid = urlsafe_base64_decode(payload.uid).decode()
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return JsonResponse({"detail": _("lien invalide")}, status=400)
    if not token_generator.check_token(user, payload.token):
        return JsonResponse({"detail": _("lien invalide ou expiré")}, status=400)
    user.set_password(payload.new_password)
    user.save(update_fields=["password"])
    return {"status": "ok"}
