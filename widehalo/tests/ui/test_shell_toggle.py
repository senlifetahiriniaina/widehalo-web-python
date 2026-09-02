"""Bascule shell legacy <-> nouveau shell (Sprint 1 / L0 de la refonte UX,
strangler pattern — cf. docs/planning/2026-refonte-ux-sprints.md §5) :
`apps.core.views.pages.toggle_shell`/`launchpad`. Meme idiome que
`tests/ui/test_menu_rbac.py` pour la connexion + filtrage RBAC."""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from django.test import Client

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_dashboard_stays_legacy_by_default() -> None:
    tenant = Tenant.objects.create(code="SHELL-1", name="Shell Tenant 1")
    user = User.objects.create_user(email="shell1@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b"app-shell" in response.content


def test_toggle_shell_then_dashboard_redirects_to_launchpad() -> None:
    tenant = Tenant.objects.create(code="SHELL-2", name="Shell Tenant 2")
    user = User.objects.create_user(email="shell2@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    toggle_response = client.post("/settings/shell/toggle/", {"next": "/launchpad/"})
    assert toggle_response.status_code == 302
    assert toggle_response["Location"] == "/launchpad/"

    dashboard_response = client.get("/dashboard/")
    assert dashboard_response.status_code == 302
    assert dashboard_response["Location"] == "/launchpad/"


def test_toggle_shell_rejects_external_next_url() -> None:
    """Jamais d'open redirect : un `next` qui ne commence pas par `/` est
    ignore (repli sur le referrer puis le tableau de bord)."""
    tenant = Tenant.objects.create(code="SHELL-3", name="Shell Tenant 3")
    user = User.objects.create_user(email="shell3@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    response = client.post("/settings/shell/toggle/", {"next": "https://evil.example/"})
    assert response.status_code == 302
    assert response["Location"] != "https://evil.example/"


def test_launchpad_shows_only_role_visible_apps() -> None:
    """Meme matrice RBAC que le menu legacy (`ROLE_APP_PERMISSIONS`) —
    `magasinier` voit stocks/logistics, jamais CRM/Comptabilite (memes
    assertions que test_menu_rbac.py::test_magasinier_does_not_see_crm_
    or_accounting_links, sur le nouveau shell)."""
    tenant = Tenant.objects.create(code="SHELL-4", name="Shell Tenant 4")
    user = User.objects.create_user(email="shell4@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="magasinier")
    user.groups.add(group)
    client = _login_with_tenant(tenant, user)
    client.post("/settings/shell/toggle/")

    soup = BeautifulSoup(client.get("/launchpad/").content, "html.parser")
    assert soup.find("a", href="/stocks/") is not None
    assert soup.find("a", href="/logistics/") is not None
    assert soup.find("a", href="/crm/") is None
    assert soup.find("a", href="/accounting/") is None


def test_notifications_bell_fragment_returns_unread_count() -> None:
    from apps.core.models.notification import Notification

    tenant = Tenant.objects.create(code="SHELL-5", name="Shell Tenant 5")
    user = User.objects.create_user(email="shell5@example.com", password="Str0ngPassw0rd!23")
    Notification.objects.create(
        tenant_id=tenant.id, user=user, notification_type="test.notification", payload={}
    )
    client = _login_with_tenant(tenant, user)

    response = client.get("/notifications/bell/")
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    badge = soup.find(id="notif-count")
    assert badge is not None
    assert badge.get_text(strip=True) == "1"
    assert "hidden" not in badge.get("class", [])


def test_notifications_bell_renders_contextual_action_link() -> None:
    """Notification contextuelle avec action (Sprint 3 / L2, cf.
    docs/planning/2026-refonte-ux-sprints.md §5) : convention
    payload.action_url/action_label."""
    from apps.core.models.notification import Notification

    tenant = Tenant.objects.create(code="SHELL-6", name="Shell Tenant 6")
    user = User.objects.create_user(email="shell6@example.com", password="Str0ngPassw0rd!23")
    Notification.objects.create(
        tenant_id=tenant.id,
        user=user,
        notification_type="sales.order_confirmed",
        payload={
            "message": "Commande confirmée",
            "action_url": "/sales/orders/abc/",
            "action_label": "Voir la commande",
        },
    )
    client = _login_with_tenant(tenant, user)

    soup = BeautifulSoup(client.get("/notifications/bell/").content, "html.parser")
    action_link = soup.find("a", href="/sales/orders/abc/")
    assert action_link is not None
    assert action_link.get_text(strip=True) == "Voir la commande"
