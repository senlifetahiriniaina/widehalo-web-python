"""Cahier des charges WideHalo v3, Phase 1, §6.5 : « toute connexion et
tout echec d'authentification » doit etre journalise. Ecart confirme par
l'audit (docs/audit/2026-09-cahier-des-charges-v3-audit.md, §9) :
ACTION_LOGIN/ACTION_LOGIN_FAILED existaient comme constantes sans jamais
etre ecrites — corrige par `apps.core.audit_signals`
(`_on_user_logged_in`/`_on_user_login_failed`), branche sur les signaux
standards Django `user_logged_in`/`user_login_failed`.

Passe par le client de test Django (pile middleware complete, y compris
`AuthenticationMiddleware`/session) plutot que par un `RequestFactory` nu
— `authenticate()` route vers `AxesBackend` (verrouillage apres echecs
repetes), qui a besoin d'un `request.session` reellement present pour
fonctionner, exactement comme en production."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.audit import AuditLog
from apps.core.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_successful_login_is_audited() -> None:
    user = UserFactory()
    client = Client()

    response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    entry = AuditLog.objects.filter(action=AuditLog.ACTION_LOGIN, object_id=str(user.id)).first()
    assert entry is not None
    assert entry.actor_id == user.id


def test_failed_login_is_audited_without_leaking_password() -> None:
    user = UserFactory()
    client = Client()

    response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": "wrong-password"},
        content_type="application/json",
    )

    assert response.status_code == 401
    entry = (
        AuditLog.objects.filter(action=AuditLog.ACTION_LOGIN_FAILED).order_by("-created_at").first()
    )
    assert entry is not None
    assert entry.metadata["attempted_username"] == user.email
    assert "wrong-password" not in str(entry.metadata)
    assert "wrong-password" not in str(entry.changes)


def test_unknown_email_login_attempt_is_audited() -> None:
    client = Client()

    response = client.post(
        "/api/v1/auth/login",
        {"email": "nobody@example.com", "password": "whatever"},
        content_type="application/json",
    )

    assert response.status_code == 401
    entry = (
        AuditLog.objects.filter(action=AuditLog.ACTION_LOGIN_FAILED).order_by("-created_at").first()
    )
    assert entry is not None
    assert entry.metadata["attempted_username"] == "nobody@example.com"


def test_session_login_view_is_also_audited() -> None:
    # Le flux session (`apps.core.views.auth_web.login_view`, `/login/`)
    # appelle `django.contrib.auth.login()` directement — le signal
    # `user_logged_in` part donc "naturellement", sans le `send()` explicite
    # ajoute cote JWT (cf. `apps.core.services.auth.login`). Ce test confirme
    # que les DEUX flux alimentent bien le meme point d'ecoute unique.
    user = UserFactory()
    client = Client()

    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})

    assert response.status_code == 302
    entry = AuditLog.objects.filter(action=AuditLog.ACTION_LOGIN, object_id=str(user.id)).first()
    assert entry is not None
