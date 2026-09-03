"""Sprint 10 (L6 Personnalisation & offline, cf.
docs/planning/2026-refonte-ux-sprints.md) : activation reelle de
`User.preferred_language` (`apps.core.middleware.UserLocaleMiddleware`),
formulaire de bascule de langue (`set_language_view`), preferences
theme/densite (`set_preference_view`), et rendu serveur du theme resolu
(`<html data-theme="...">`, cf. `apps.core.context_processors.account`)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils import translation

from apps.core.models.tenant import Tenant
from apps.core.models.user import User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _existing_tenant() -> Tenant:
    # OnboardingMiddleware exige un Tenant deja existant avant tout ecran
    # authentifie normal — meme sequencement que test_account_menu.py.
    return Tenant.objects.create(code="PERSO-TEST", name="Test personnalisation")


def _logged_in_client(user: User) -> Client:
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content
    return client


@pytest.fixture
def user_mg() -> User:
    return User.objects.create_user(
        email="mg-user@example.com", password="Str0ngPassw0rd!23", preferred_language="mg"
    )


@pytest.fixture
def user_default() -> User:
    return User.objects.create_user(email="fr-user@example.com", password="Str0ngPassw0rd!23")


# --- UserLocaleMiddleware ----------------------------------------------


def test_authenticated_user_with_preferred_language_gets_it_activated(user_mg: User) -> None:
    client = _logged_in_client(user_mg)
    try:
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert translation.get_language() == "mg"
    finally:
        translation.deactivate()


def test_anonymous_visitor_falls_back_to_locale_middleware_default() -> None:
    client = Client()
    response = client.get("/login/")
    assert response.status_code == 200
    # Aucune preference utilisateur : LocaleMiddleware seul decide (defaut
    # LANGUAGE_CODE="fr" en l'absence de cookie/Accept-Language).
    assert translation.get_language() == "fr"


def test_authenticated_user_without_explicit_preference_keeps_locale_middleware_choice(
    user_default: User,
) -> None:
    # `preferred_language` a une valeur par defaut ("fr") posee par le
    # modele -- ce test verifie seulement que la requete ne plante pas et
    # respecte cette valeur, jamais un cas "sans preference du tout".
    client = _logged_in_client(user_default)
    try:
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert translation.get_language() == "fr"
    finally:
        translation.deactivate()


# --- set_language_view ---------------------------------------------------


def test_set_language_persists_preferred_language_for_authenticated_user(
    user_default: User,
) -> None:
    client = _logged_in_client(user_default)
    response = client.post("/i18n/setlang/", {"language": "mg", "next": "/dashboard/"})
    assert response.status_code == 302
    assert response.url == "/dashboard/"

    user_default.refresh_from_db()
    assert user_default.preferred_language == "mg"


def test_set_language_ignores_unknown_language_code(user_default: User) -> None:
    client = _logged_in_client(user_default)
    response = client.post("/i18n/setlang/", {"language": "xx", "next": "/dashboard/"})
    assert response.status_code == 302

    user_default.refresh_from_db()
    assert user_default.preferred_language == "fr"


def test_set_language_rejects_external_redirect() -> None:
    client = Client()
    response = client.post(
        "/i18n/setlang/", {"language": "en", "next": "https://evil.example.com/"}
    )
    assert response.status_code == 302
    assert response.url == "/"


def test_set_language_get_is_not_allowed() -> None:
    client = Client()
    response = client.get("/i18n/setlang/")
    assert response.status_code == 405


# --- set_preference_view (theme/densite) ----------------------------------


def test_set_preference_saves_theme(user_default: User) -> None:
    client = _logged_in_client(user_default)
    response = client.post("/settings/preferences/", {"theme": "dark", "next": "/dashboard/"})
    assert response.status_code == 302

    user_default.refresh_from_db()
    assert user_default.theme == "dark"


def test_set_preference_saves_density(user_default: User) -> None:
    client = _logged_in_client(user_default)
    response = client.post("/settings/preferences/", {"density": "compact", "next": "/dashboard/"})
    assert response.status_code == 302

    user_default.refresh_from_db()
    assert user_default.density == "compact"


def test_set_preference_ignores_invalid_values(user_default: User) -> None:
    client = _logged_in_client(user_default)
    client.post("/settings/preferences/", {"theme": "not-a-theme"})

    user_default.refresh_from_db()
    assert user_default.theme == "system"


def test_set_preference_requires_authentication() -> None:
    client = Client()
    response = client.post("/settings/preferences/", {"theme": "dark"})
    assert response.status_code == 302
    assert "/login/" in response.url


# --- Rendu serveur du theme resolu -----------------------------------------


def test_dashboard_renders_dark_theme_attribute_for_dark_user(user_default: User) -> None:
    user_default.theme = "dark"
    user_default.save(update_fields=["theme"])
    client = _logged_in_client(user_default)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    assert b'data-theme="widehalo-dark"' in response.content


def test_dashboard_renders_light_theme_attribute_for_light_user(user_default: User) -> None:
    user_default.theme = "light"
    user_default.save(update_fields=["theme"])
    client = _logged_in_client(user_default)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    assert b'data-theme="widehalo"' in response.content


def test_dashboard_falls_back_to_light_theme_for_system_default(user_default: User) -> None:
    # `theme="system"` (defaut du modele) : le rendu SERVEUR doit rester
    # "widehalo" (clair) -- la resolution `prefers-color-scheme` reelle
    # n'est qu'une amelioration cote client (cf. base.html), jamais la
    # source de verite du rendu initial.
    assert user_default.theme == "system"
    client = _logged_in_client(user_default)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    assert b'data-theme="widehalo"' in response.content
    assert b'data-theme="widehalo-dark"' not in response.content


def test_dashboard_applies_density_body_class(user_default: User) -> None:
    user_default.density = "compact"
    user_default.save(update_fields=["density"])
    client = _logged_in_client(user_default)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    assert b"density-compact" in response.content
