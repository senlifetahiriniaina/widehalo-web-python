"""Fixtures Playwright partagees pour les tests e2e (couche 1, §8 du CDC).
Le login passe reellement par le formulaire HTML (`/login/`) plutot que
par une injection de cookie de session — c'est lui-meme l'un des
parcours critiques a couvrir (§5, connexion)."""

from __future__ import annotations

import os

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership

# Playwright (API sync) laisse une boucle asyncio active dans le thread
# principal pendant toute la duree de vie du navigateur (session scope) :
# Django detecte alors a tort un contexte async lors des acces ORM de
# setup/teardown des tests (`SynchronousOnlyOperation`). Ce contournement
# est documente comme necessaire pour combiner pytest-django et
# pytest-playwright en API synchrone — sans impact production (jamais lu
# hors des tests e2e).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

PASSWORD = "Str0ngPassw0rd!23"


@pytest.fixture(scope="session", autouse=True)
def _create_test_database_before_playwright(django_db_setup):
    """Force la creation de la base de test AVANT le premier lancement de
    Chromium : Playwright (API sync) laisse une boucle asyncio "active"
    dans le thread principal, ce qui fait echouer le
    `SynchronousOnlyOperation` de Django si `setup_databases()` (session
    scope, execute a la premiere demande de `db`/`live_server`) se
    declenche apres coup."""
    return


_PREINSTALLED_CHROMIUM = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Certains environnements de developpement pre-installent Chromium a
    une revision qui ne correspond pas a celle attendue par la version pip
    de `playwright` — on pointe alors explicitement vers ce binaire deja
    present. En CI (ou tout environnement standard), `playwright install`
    fournit une revision compatible : ce chemin n'existe pas et on laisse
    pytest-playwright utiliser son propre binaire, sans le forcer."""
    if os.path.exists(_PREINSTALLED_CHROMIUM):
        return {**browser_type_launch_args, "executable_path": _PREINSTALLED_CHROMIUM}
    return browser_type_launch_args


@pytest.fixture
def e2e_tenant_and_user(live_server):
    """Depend sur `live_server` (pas `db`) : celui-ci active deja
    `transactional_db`, necessaire pour que le thread du serveur de test
    et le thread Playwright voient les memes ecritures committees."""
    tenant = Tenant.objects.create(code="E2E", name="E2E Tenant")
    user = User.objects.create_user(email="e2e@example.com", password=PASSWORD)
    UserTenantMembership.objects.create(user=user, tenant=tenant, is_default=True)
    return tenant, user


@pytest.fixture
def logged_in_page(page, live_server, e2e_tenant_and_user):
    _tenant, user = e2e_tenant_and_user
    page.goto(f"{live_server.url}/login/")
    page.fill("#email", user.email)
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/dashboard/")
    return page
