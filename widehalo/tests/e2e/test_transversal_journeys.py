"""Parcours transversaux du Lot 1 (deja verifies via `django.test.Client`+
BeautifulSoup a l'etape 14) — repris ici en Playwright reel (couche 1,
§8 du CDC) : connexion, creation de partenaire, recherche globale."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.playwright


def test_login_journey(page, live_server, e2e_tenant_and_user) -> None:
    _tenant, user = e2e_tenant_and_user
    page.goto(f"{live_server.url}/login/")
    page.fill("#email", user.email)
    page.fill("#password", "Str0ngPassw0rd!23")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/dashboard/")
    assert page.url == f"{live_server.url}/dashboard/"


def test_partner_creation_journey(logged_in_page, live_server) -> None:
    page = logged_in_page
    page.goto(f"{live_server.url}/partners/new/")
    page.fill("#name", "Textiles Playwright")
    page.click("button[type=submit]")
    page.wait_for_selector("#credit_limit_mga")
    page.click("button[type=submit]")
    # Le formulaire de l'assistant est en `hx-post` : la redirection finale
    # (`partners:detail`) est suivie par htmx en AJAX et son contenu est
    # swape dans le conteneur, sans navigation de page complete — l'URL du
    # navigateur ne change donc pas, contrairement a un `<form>` classique.
    page.wait_for_selector("text=Textiles Playwright")
    assert "Textiles Playwright" in page.content()


def test_global_search_journey(logged_in_page, live_server) -> None:
    page = logged_in_page
    page.goto(f"{live_server.url}/search/")
    assert page.title() != ""
