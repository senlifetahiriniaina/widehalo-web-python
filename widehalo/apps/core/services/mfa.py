"""MFA TOTP — obligatoire pour les roles admin/direction/comptable/rh
(cf. settings.CORE_MFA_REQUIRED_ROLES). Un seul facteur (TOTP) implemente
dans ce lot ; SMS/WebAuthn restent hors perimetre V1."""

from __future__ import annotations

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


def verify_token(user: User, token: str) -> bool:
    for device in devices_for_user(user, confirmed=True):
        if isinstance(device, TOTPDevice) and device.verify_token(token):
            return True
    return False
