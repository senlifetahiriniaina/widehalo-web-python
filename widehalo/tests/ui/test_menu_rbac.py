from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from django.test import Client
from django_otp.oath import totp

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def _login_with_tenant_mfa_verified(tenant: Tenant, user: User) -> Client:
    """`admin`/superutilisateur sont soumis a MFA obligatoire
    (`CORE_MFA_REQUIRED_ROLES`/`user.is_superuser`, cf.
    `apps.core.middleware.MFAEnforcementMiddleware`) — sans enrolement +
    verification TOTP, tout GET hors des chemins exemptes redirige (302)
    vers `/mfa/` au lieu de rendre la page, meme idiome que
    `tests/ui/test_logistics_screens.py::test_settings_hub_links_to_logistics_config`."""
    client = _login_with_tenant(tenant, user)
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content
    return client


def test_magasinier_does_not_see_crm_or_accounting_links() -> None:
    """`magasinier` n'a acces qu'a stocks/mrp/catalog/logistics/reporting/
    strategy/helpdesk (cf. `ROLE_APP_PERMISSIONS`) — les liens/groupes CRM
    et Comptabilite doivent etre absents du HTML rendu."""
    tenant = Tenant.objects.create(code="RBAC-MENU-1", name="RBAC Menu Tenant 1")
    user = User.objects.create_user(email="magasinier@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="magasinier")
    user.groups.add(group)

    client = _login_with_tenant(tenant, user)
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    # Scope elargi a tout `ul.app-menu` (pas seulement `.app-menu-groups`) :
    # le groupe "Pour tous" (reporting/strategy/helpdesk) est desormais un
    # `<li>` de premier niveau, sibling de "Modules metier", plus imbrique
    # dans `.app-menu-groups` (chantier "Assistant IA en popup...").
    menu = soup.find("ul", class_="app-menu")

    assert menu.find("a", href="/stocks/") is not None
    assert menu.find("a", href="/logistics/") is not None

    assert menu.find("a", href="/crm/") is None
    assert menu.find("a", href="/accounting/") is None
    assert menu.find("a", href="/payroll/") is None
    # Le groupe "Commercial" entier doit disparaitre (aucun de ses 3 liens
    # n'est visible pour ce role).
    assert "Commercial" not in menu.get_text()
    # Le groupe "Achats et logistique" reste visible (au moins un lien
    # l'est).
    assert "Achats et logistique" in menu.get_text()


def test_admin_sees_all_module_links_it_is_granted_by_the_rbac_matrix() -> None:
    """Role `admin` : tous les liens dont `ROLE_APP_PERMISSIONS["admin"]`
    porte effectivement `"view"` restent presents, plus le registre des
    risques (special-case `CUSTOM_PERMISSIONS`, cf. `visible_app_labels_for`).

    Note : `ROLE_APP_PERMISSIONS["admin"]` ne porte PAS de cle `"payroll"`
    (ni `"direction"` d'ailleurs) — seul `rh` (+ "view" pour `resp_
    production`/`chef_atelier`/`resp_commercial`) recoit l'acces au module
    `payroll` dans la matrice actuelle. C'est le comportement REEL de la
    politique existante (hors perimetre UXR2 de la modifier) : `/payroll/`
    est donc volontairement absent de la liste ci-dessous — seul un
    superutilisateur (qui contourne la matrice, cf. `test_superuser_sees_
    all_module_links_even_without_role_groups` ci-dessous) voit vraiment
    les 18 liens."""
    tenant = Tenant.objects.create(code="RBAC-MENU-2", name="RBAC Menu Tenant 2")
    user = User.objects.create_user(email="admin-role@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)

    client = _login_with_tenant_mfa_verified(tenant, user)
    resp = client.get("/dashboard/")
    soup = BeautifulSoup(resp.content, "html.parser")
    # Scope elargi a tout `ul.app-menu` (pas seulement `.app-menu-groups`) :
    # le groupe "Pour tous" (reporting/strategy/helpdesk) est desormais un
    # `<li>` de premier niveau, sibling de "Modules metier", plus imbrique
    # dans `.app-menu-groups` (chantier "Assistant IA en popup...").
    menu = soup.find("ul", class_="app-menu")

    for href in (
        "/reporting/",
        "/strategy/",
        "/helpdesk/",
        "/crm/",
        "/sales/",
        "/feasibility/",
        "/purchase/",
        "/stocks/",
        "/logistics/",
        "/mrp/",
        "/patronage/",
        "/accounting/",
        "/financing/",
        "/automation/",
        "/presence/",
        "/projects/",
        "/risks/",
    ):
        assert menu.find("a", href=href) is not None, href
    # `payroll` reste absent pour ce role precis (cf. note ci-dessus).
    assert menu.find("a", href="/payroll/") is None


def test_superuser_sees_all_module_links_even_without_role_groups() -> None:
    tenant = Tenant.objects.create(code="RBAC-MENU-3", name="RBAC Menu Tenant 3")
    user = User.objects.create_superuser(
        email="superuser@example.com", password="Str0ngPassw0rd!23"
    )

    client = _login_with_tenant_mfa_verified(tenant, user)
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    # Scope elargi a tout `ul.app-menu` (pas seulement `.app-menu-groups`) :
    # le groupe "Pour tous" (reporting/strategy/helpdesk) est desormais un
    # `<li>` de premier niveau, sibling de "Modules metier", plus imbrique
    # dans `.app-menu-groups` (chantier "Assistant IA en popup...").
    menu = soup.find("ul", class_="app-menu")

    assert menu.find("a", href="/crm/") is not None
    assert menu.find("a", href="/risks/") is not None
    # Contrairement au role `admin` (cf. test ci-dessus), le superutilisateur
    # contourne entierement la matrice `ROLE_APP_PERMISSIONS` — `payroll`
    # (absent de `ROLE_APP_PERMISSIONS["admin"]`) reste donc bien visible ici.
    assert menu.find("a", href="/payroll/") is not None


def test_collaborateur_role_does_not_see_risks_link() -> None:
    """`collaborateur` (role par defaut) ne recoit ni `core.view_riskitem`
    ni aucun autre acces au registre des risques (cf.
    `_RISK_ADD_VIEW_ROLES`) — le lien « Registre des risques » doit rester
    absent, contrairement a `acheteur`/`resp_production`/`resp_commercial`/
    `rh`."""
    tenant = Tenant.objects.create(code="RBAC-MENU-4", name="RBAC Menu Tenant 4")
    user = User.objects.create_user(email="collaborateur@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="collaborateur")
    user.groups.add(group)

    client = _login_with_tenant(tenant, user)
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    # Scope elargi a tout `ul.app-menu` (pas seulement `.app-menu-groups`) :
    # le groupe "Pour tous" (reporting/strategy/helpdesk) est desormais un
    # `<li>` de premier niveau, sibling de "Modules metier", plus imbrique
    # dans `.app-menu-groups` (chantier "Assistant IA en popup...").
    menu = soup.find("ul", class_="app-menu")

    assert menu.find("a", href="/risks/") is None
    assert menu.find("a", href="/projects/") is not None


def test_acheteur_role_sees_risks_link() -> None:
    """`acheteur` fait partie de `_RISK_ADD_VIEW_ROLES` (cf.
    `rbac_policy.CUSTOM_PERMISSIONS`) : le lien risques doit apparaitre
    meme si `core` n'apparait jamais comme cle de `ROLE_APP_PERMISSIONS`."""
    tenant = Tenant.objects.create(code="RBAC-MENU-5", name="RBAC Menu Tenant 5")
    user = User.objects.create_user(email="acheteur@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="acheteur")
    user.groups.add(group)

    client = _login_with_tenant(tenant, user)
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    # Scope elargi a tout `ul.app-menu` (pas seulement `.app-menu-groups`) :
    # le groupe "Pour tous" (reporting/strategy/helpdesk) est desormais un
    # `<li>` de premier niveau, sibling de "Modules metier", plus imbrique
    # dans `.app-menu-groups` (chantier "Assistant IA en popup...").
    menu = soup.find("ul", class_="app-menu")

    assert menu.find("a", href="/risks/") is not None
