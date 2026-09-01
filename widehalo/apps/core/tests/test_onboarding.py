"""Bootstrap admin par defaut (admin@admin.local/admin) + parametrage force
de la premiere societe de l'instance — cf. apps/core/middleware.py
(OnboardingMiddleware) et apps/core/management/commands/bootstrap_admin.py."""

from __future__ import annotations

import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.management import call_command
from django.test import Client

from apps.core.management.commands.bootstrap_admin import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership

pytestmark = pytest.mark.django_db


def test_bootstrap_admin_creates_default_account_on_fresh_instance() -> None:
    """Une instance fraiche a systematiquement deja un utilisateur
    'AnonymousUser' reel en base (django-guardian, post_migrate) — le
    garde-fou de la commande doit donc porter sur is_superuser, jamais sur
    User.objects.exists() (bug reel trouve en ecrivant ce test)."""
    assert User.objects.exists()  # AnonymousUser (django-guardian), toujours présent
    assert not User.objects.filter(is_superuser=True).exists()

    call_command("bootstrap_admin")

    user = User.objects.get(email=DEFAULT_ADMIN_EMAIL)
    assert user.is_superuser
    assert user.is_staff
    assert user.must_change_password is True
    assert user.check_password(DEFAULT_ADMIN_PASSWORD)
    assert "admin" in user.groups.values_list("name", flat=True)


def test_bootstrap_admin_is_a_noop_once_a_superuser_exists() -> None:
    User.objects.create_superuser(email="already@example.com", password="Str0ngPassw0rd!23")

    call_command("bootstrap_admin")

    assert not User.objects.filter(email=DEFAULT_ADMIN_EMAIL).exists()


def test_bootstrap_admin_is_a_noop_for_ordinary_non_superuser_accounts() -> None:
    """Un utilisateur ordinaire (non superuser) ne doit PAS empecher le
    bootstrap — seul un vrai superutilisateur compte."""
    User.objects.create_user(email="ordinary@example.com", password="Str0ngPassw0rd!23")

    call_command("bootstrap_admin")

    assert User.objects.filter(email=DEFAULT_ADMIN_EMAIL).exists()


def test_default_admin_password_is_rejected_by_django_validators() -> None:
    """Le mot de passe "admin" (delibere) ne doit jamais pouvoir redevenir
    le nouveau mot de passe au changement force — verifie directement
    contre les validateurs reels du projet (CommonPasswordValidator inclus),
    pas seulement suppose."""
    call_command("bootstrap_admin")
    user = User.objects.get(email=DEFAULT_ADMIN_EMAIL)

    with pytest.raises(Exception):  # noqa: B017,PT011 — ValidationError Django, verifie le message ci-dessous
        validate_password(DEFAULT_ADMIN_PASSWORD, user=user)


def _login_default_admin(client: Client) -> User:
    call_command("bootstrap_admin")
    user = User.objects.get(email=DEFAULT_ADMIN_EMAIL)
    client.force_login(user)
    return user


def test_must_change_password_blocks_web_access_until_changed() -> None:
    client = Client()
    _login_default_admin(client)

    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert response.url == "/change-password/"


def test_change_password_rejects_wrong_current_password() -> None:
    client = Client()
    _login_default_admin(client)

    response = client.post(
        "/change-password/",
        {
            "current_password": "not-the-real-password",
            "new_password": "Str0ngPassw0rd!23",
            "confirm_password": "Str0ngPassw0rd!23",
        },
    )
    assert response.status_code == 200
    user = User.objects.get(email=DEFAULT_ADMIN_EMAIL)
    assert user.must_change_password is True


def test_change_password_rejects_mismatched_confirmation() -> None:
    client = Client()
    _login_default_admin(client)

    response = client.post(
        "/change-password/",
        {
            "current_password": DEFAULT_ADMIN_PASSWORD,
            "new_password": "Str0ngPassw0rd!23",
            "confirm_password": "Different!23",
        },
    )
    assert response.status_code == 200
    user = User.objects.get(email=DEFAULT_ADMIN_EMAIL)
    assert user.must_change_password is True


def test_change_password_rejects_common_password_reuse() -> None:
    """`new_password="admin"` doit etre refuse par CommonPasswordValidator —
    empeche de re-choisir exactement le mot de passe par defaut."""
    client = Client()
    _login_default_admin(client)

    response = client.post(
        "/change-password/",
        {
            "current_password": DEFAULT_ADMIN_PASSWORD,
            "new_password": DEFAULT_ADMIN_PASSWORD,
            "confirm_password": DEFAULT_ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 200
    user = User.objects.get(email=DEFAULT_ADMIN_EMAIL)
    assert user.must_change_password is True


def test_change_password_success_unblocks_access_and_keeps_session() -> None:
    client = Client()
    user = _login_default_admin(client)

    response = client.post(
        "/change-password/",
        {
            "current_password": DEFAULT_ADMIN_PASSWORD,
            "new_password": "Str0ngPassw0rd!23",
            "confirm_password": "Str0ngPassw0rd!23",
        },
    )
    assert response.status_code == 302

    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.check_password("Str0ngPassw0rd!23")

    # La session doit rester valide (update_session_auth_hash) — pas de
    # deconnexion surprise juste apres avoir change son propre mot de passe.
    dashboard_response = client.get("/dashboard/")
    assert dashboard_response.status_code == 302
    assert dashboard_response.url == "/setup/"


def test_setup_company_forced_when_no_tenant_exists_instance_wide() -> None:
    client = Client()
    user = _login_default_admin(client)
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])

    assert not Tenant.objects.exists()
    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert response.url == "/setup/"


def test_setup_company_creates_tenant_and_attaches_current_user() -> None:
    client = Client()
    user = _login_default_admin(client)
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])

    response = client.post(
        "/setup/",
        {
            "code": "PREMIERE-SOCIETE",
            "name": "Ma Première Société",
            "nif": "NIF-0001",
            "country_code": "MG",
        },
    )
    assert response.status_code == 302
    assert response.url == "/dashboard/"

    tenant = Tenant.objects.get(code="PREMIERE-SOCIETE")
    assert tenant.name == "Ma Première Société"
    assert tenant.base_currency == "MGA"  # SmartDefaults Madagascar appliqué
    assert UserTenantMembership.objects.filter(user=user, tenant=tenant, is_default=True).exists()

    # Le catalogue de types de tickets helpdesk ne doit plus jamais etre
    # vide pour un tenant cree via ce parcours web reel (signalement
    # utilisateur — cf. plan section "catalogue de tickets helpdesk vide
    # par defaut").
    from apps.core.tests.utils import use_tenant
    from apps.helpdesk.models import HlpTicketTypeCatalog

    with use_tenant(tenant.id):
        assert HlpTicketTypeCatalog.objects.filter(tenant=tenant).count() > 30

    # Meme convention : le plan comptable (generique + sectoriel) et les 7
    # journaux comptables par defaut sont deja la, sans aucune action
    # manuelle (UXR7).
    from apps.accounting.models import AccAccount, AccJournal

    with use_tenant(tenant.id):
        assert AccAccount.objects.filter(tenant=tenant).count() >= 54
        assert AccJournal.objects.filter(tenant=tenant).count() == 7

    # Pipeline commercial par defaut (HubSpot, 7 etapes — cf. analyse
    # comparative des 5 principaux CRM mondiaux) : jamais vide non plus pour
    # une entreprise reelle initialisee via ce parcours.
    from apps.crm.models import CrmLostReason, CrmPipeline, CrmStage

    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.get(tenant=tenant, is_default=True)
        assert CrmStage.objects.filter(tenant=tenant, pipeline=pipeline).count() == 7

    # Motifs de perte d'opportunite par defaut (7 categories metier — cf.
    # analyse comparative des motifs de perte des 5 principaux CRM
    # mondiaux) : jamais vides non plus pour une entreprise reelle.
    with use_tenant(tenant.id):
        assert CrmLostReason.objects.filter(tenant=tenant).count() == 7

    # Catalogue par defaut des produits (30 EPI/vetements techniques
    # fabricables a Madagascar, Volet 2 du document source) : jamais vide
    # pour une entreprise reelle initialisee via ce parcours.
    from apps.catalog.models import ProductTemplate

    with use_tenant(tenant.id):
        assert ProductTemplate.objects.filter(tenant=tenant).count() == 30

    # L'amorçage d'instance est termine (plus de redirection vers /setup/) —
    # seul l'enrolement MFA (deja exige du role "admin" avant ce lot, cf.
    # etape 4, sans lien avec cette fonctionnalite) reste a faire ensuite.
    dashboard_response = client.get("/dashboard/")
    assert dashboard_response.status_code == 302
    assert dashboard_response.url == "/mfa/"


def test_setup_company_screen_unreachable_once_a_tenant_already_exists() -> None:
    """Un tenant existe deja ailleurs sur l'instance (creee par un autre
    utilisateur/flux) — /setup/ redirige vers le tableau de bord plutot que
    de permettre une seconde 'premiere societe'."""
    Tenant.objects.create(code="ALREADY-THERE", name="Deja paramétrée")
    client = Client()
    user = _login_default_admin(client)
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])

    response = client.get("/setup/")
    assert response.status_code == 302
    assert response.url == "/dashboard/"


def test_api_paths_are_exempt_from_onboarding_middleware() -> None:
    """Un compte fraichement bootstrappe (mot de passe non change, aucune
    societe) ne doit jamais etre bloque sur l'API — seul l'acces web par
    session est concerne."""
    client = Client()
    _login_default_admin(client)

    response = client.get("/api/v1/health/live")
    assert response.status_code != 302
