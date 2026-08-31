"""MFA TOTP — obligatoire pour les roles admin/direction/comptable/rh
(cf. settings.CORE_MFA_REQUIRED_ROLES). Un seul facteur (TOTP) implemente
dans ce lot ; SMS/WebAuthn restent hors perimetre V1."""

from __future__ import annotations

import base64
import io

import qrcode
from django.conf import settings
from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.models.user import User


def mfa_required_for_user(user: User) -> bool:
    role_codes = set(user.groups.values_list("name", flat=True))
    return bool(role_codes & set(settings.CORE_MFA_REQUIRED_ROLES)) or user.is_superuser


def has_confirmed_device(user: User) -> bool:
    return any(devices_for_user(user, confirmed=True))


def enroll_device(user: User) -> TOTPDevice:
    """Cree (ou reutilise) un device TOTP non confirme pour l'utilisateur,
    a presenter comme QR code (device.config_url)."""
    device, _created = TOTPDevice.objects.get_or_create(
        user=user, confirmed=False, defaults={"name": "default"}
    )
    return device


def confirm_device(device: TOTPDevice, token: str) -> bool:
    if device.verify_token(token):
        device.confirmed = True
        device.save(update_fields=["confirmed"])
        return True
    return False


def verify_token(user: User, token: str) -> TOTPDevice | None:
    """Retourne le device confirme dont `token` valide, sinon `None` — un
    modele Django est toujours vrai/`bool()`, donc `not verify_token(...)`
    reste un test de validite correct pour tout appelant qui n'a besoin que
    d'un booleen (ex. l'API `/api/v1/auth/mfa/verify`). L'ecran web
    (`apps.core.views.auth_web.mfa_view`) a en plus besoin du device
    lui-meme pour appeler `django_otp.login(request, device)`."""
    for device in devices_for_user(user, confirmed=True):
        if isinstance(device, TOTPDevice) and device.verify_token(token):
            return device
    return None


def generate_totp_qr_data_uri(device: TOTPDevice) -> str:
    """QR code PNG de `device.config_url` (URI otpauth://), encode en data
    URI pour affichage direct via `<img src="...">` — aucun fichier ecrit
    sur disque, aucun couplage a `core.services.documents`. Meme
    bibliotheque `qrcode` deja utilisee par `apps.stocks.services.barcodes`
    (premiere utilisation reelle, ST7), mais pas la meme fonction : celle-ci
    encode une URI otpauth, pas un identifiant interne stocks."""
    image = qrcode.make(device.config_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
