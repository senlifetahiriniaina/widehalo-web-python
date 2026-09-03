from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.http import HttpRequest, JsonResponse
from django.test import RequestFactory

from apps.core.models.user import User
from apps.core.services.permissions import require_permission

pytestmark = pytest.mark.django_db


def _fake_request(user: User) -> HttpRequest:
    request = RequestFactory().get("/api/v1/fake")
    request.auth = user
    return request


@require_permission("core.change_tenant")
def _protected_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def test_authenticated_user_without_permission_gets_403() -> None:
    user = User.objects.create_user(email="noperm@example.com", password="Str0ngPassw0rd!23")
    response = _protected_view(_fake_request(user))
    assert response.status_code == 403


def test_anonymous_request_gets_401() -> None:
    request = RequestFactory().get("/api/v1/fake")
    request.auth = None
    response = _protected_view(request)
    assert response.status_code == 401


def test_user_with_group_permission_is_allowed() -> None:
    user = User.objects.create_user(email="withperm@example.com", password="Str0ngPassw0rd!23")
    group = Group.objects.create(name="test-group-with-perm")
    permission = Permission.objects.get(codename="change_tenant", content_type__app_label="core")
    group.permissions.add(permission)
    user.groups.add(group)

    response = _protected_view(_fake_request(user))
    assert response.status_code == 200


def test_load_roles_creates_thirteen_standard_roles() -> None:
    """13 depuis le chantier module Simulation financière (cahier §13.6) :
    `controleur_gestion` ajouté — cf. docs/RBAC.md §2 pour le raisonnement
    de cet ajout, le second depuis les 11 rôles "V1 acquis du CDC" du
    Lot 1/Lot 2 (le premier étant `caissier`, chantier module POS)."""
    from django.conf import settings
    from django.core.management import call_command

    call_command("load_roles")
    for code in settings.CORE_STANDARD_ROLES:
        assert Group.objects.filter(name=code).exists()
    assert len(settings.CORE_STANDARD_ROLES) == 13
