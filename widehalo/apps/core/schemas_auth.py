from __future__ import annotations

from ninja import Schema


class LoginIn(Schema):
    email: str
    password: str


class LoginOut(Schema):
    status: str  # "ok" | "mfa_required" | "mfa_enrollment_required"
    access: str | None = None
    refresh: str | None = None


class MfaVerifyIn(Schema):
    email: str
    token: str


class MfaEnrollOut(Schema):
    otpauth_url: str


class MfaConfirmIn(Schema):
    token: str


class RefreshIn(Schema):
    refresh: str


class TokenOut(Schema):
    access: str
    refresh: str


class PasswordResetRequestIn(Schema):
    email: str


class PasswordResetConfirmIn(Schema):
    uid: str
    token: str
    new_password: str
