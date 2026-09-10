"""T10 — la porte d'entree du module IA, et ce qu'elle doit vraiment tenir.

**Ce que ces tests defendent.** Avant T10, les sept ecrans de ce module
etaient routes, testes, fonctionnels — et cites par RIEN : `ai` n'etait
dans aucun groupe de `_MENU_GROUPS`, `/ai/` rendait 404, et seul le bouton
flottant d'assistance etait cable. Un ecran que personne ne peut atteindre
n'existe pas.

Reparer cela en posant un accueil qui ne serait qu'une liste de liens
n'aurait fait que deplacer le probleme : un accueil dont toutes les valeurs
sont ecrites en dur affiche la meme chose le premier jour et le millieme.
Les tests ci-dessous verifient donc DEUX proprietes distinctes — que
l'ecran est atteignable, et que ce qu'il affiche vient reellement de la
base.

**Le partage de droits n'est pas une invention de ce lot** :
`rbac_policy` reserve la permission de module `ai` a `admin`/`direction` en
ecrivant que les fonctions IA a usage large sont volontairement ouvertes a
tout utilisateur authentifie. Les tuiles suivent cette declaration.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django_otp.oath import totp

from apps.ai.models import AiAnomaly
from apps.ai.tests.factories import AiAnomalyFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


def _client_pour(role: str, email: str) -> tuple[Client, Tenant]:
    """Un utilisateur authentifie portant `role`, sur une societe active.

    **`force_login` ne suffit pas pour `admin`/`direction`.** Ces roles sont
    dans `CORE_MFA_REQUIRED_ROLES` : le middleware renvoie vers `/mfa/`, la
    reponse est un 302 vide, et une assertion sur le contenu passe ou
    echoue pour une raison qui n'a rien a voir avec ce qu'on teste. Le
    harnais enrole donc lui-meme le device TOTP — meme geste qu'a T4bis,
    et meme helper qu'a T9 (`test_t9_console_atteignable`).

    La voie facile aurait ete de ne tester le partage de droits qu'avec des
    roles sans MFA ; elle aurait laisse la tuile de budget sans aucune
    verification pour les seuls roles qui la voient."""
    tenant = Tenant.objects.create(code=f"AI-T10-{role[:6].upper()}", name="Societe T10")
    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    grant_role(user, role)
    UserTenantMembership.objects.get_or_create(user=user, tenant=tenant)

    client = Client()
    reponse = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302, reponse.content
    if mfa_service.mfa_required_for_user(user):
        client.get("/mfa/")
        device = mfa_service.enroll_device(user)
        reponse = client.post("/mfa/", {"token": str(totp(device.bin_key)).zfill(6)})
        assert reponse.status_code == 302, reponse.content

    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def test_the_module_entrance_answers_at_its_root() -> None:
    """`/ai/` rendait 404 : la route racine n'existait pas."""
    client, _ = _client_pour("resp_commercial", "t10-racine@example.com")
    reponse = client.get("/ai/")
    assert reponse.status_code == 200


def test_the_entrance_leads_to_every_screen_of_the_module() -> None:
    """Une porte qui n'ouvrirait que sur trois des sept ecrans laisserait
    les quatre autres exactement ou ils etaient."""
    client, _ = _client_pour("admin", "t10-portes@example.com")
    contenu = client.get("/ai/").content.decode()
    for chemin in (
        "/ai/assist/",
        "/ai/search/",
        "/ai/anomalies/",
        "/ai/insights/",
        "/ai/recommendations/",
        "/ai/data-query/",
        "/ai/usage/",
        "/ai/provider-consent/",
    ):
        assert f'href="{chemin}"' in contenu, f"l'accueil ne mene pas a {chemin}"


def test_the_open_anomaly_count_comes_from_the_database() -> None:
    """La falsification la plus utile de ce lot : un accueil qui afficherait
    un nombre ecrit en dur passerait tous les tests d'atteignabilite.

    On mesure donc l'ECART — la meme page, lue avant et apres l'ecriture de
    deux anomalies — plutot que la presence d'un chiffre, qui ne dirait rien
    de sa provenance."""
    client, tenant = _client_pour("resp_commercial", "t10-compteur@example.com")
    avant = client.get("/ai/").content.decode()
    assert "Aucune anomalie ouverte" in avant

    with use_tenant(tenant.id):
        for i in range(2):
            AiAnomalyFactory(
                tenant=tenant,
                check_code=f"sales.marge_{i}",
                status=AiAnomaly.STATUS_OPEN,
            )

    apres = client.get("/ai/").content.decode()
    assert "Aucune anomalie ouverte" not in apres
    assert "2 ouvertes" in apres


def test_a_closed_anomaly_is_not_counted_as_open() -> None:
    """« Ouvertes » doit vouloir dire ouvertes. Un compteur qui prendrait
    toutes les anomalies afficherait un chiffre qui ne redescend jamais, et
    l'exploitant cesserait de le regarder — la variante ACTIVE du motif
    « rien de decoratif »."""
    client, tenant = _client_pour("resp_commercial", "t10-fermee@example.com")
    with use_tenant(tenant.id):
        AiAnomalyFactory(
            tenant=tenant,
            check_code="sales.marge_traitee",
            status=AiAnomaly.STATUS_HANDLED,
        )
    assert "Aucune anomalie ouverte" in client.get("/ai/").content.decode()


def test_the_budget_tile_follows_the_module_permission() -> None:
    """Le budget est le seul ecran restreint du module, et la restriction
    vient de `rbac_policy`, pas de ce lot."""
    ordinaire, _ = _client_pour("resp_commercial", "t10-sans-droit@example.com")
    assert 'href="/ai/usage/"' not in ordinaire.get("/ai/").content.decode()

    dirigeant, _ = _client_pour("direction", "t10-avec-droit@example.com")
    assert 'href="/ai/usage/"' in dirigeant.get("/ai/").content.decode()


def test_the_missing_connector_is_announced_rather_than_discovered() -> None:
    """§12.3 : le repli est un livrable, pas une panne — mais il se dit.

    Sans connecteur, les ecrans repondent depuis le repli local. Ne pas
    l'annoncer laisserait l'exploitant juger la qualite d'une reponse sans
    savoir d'ou elle vient."""
    client, _ = _client_pour("resp_commercial", "t10-repli@example.com")
    contenu = client.get("/ai/").content.decode()
    assert "Aucun connecteur d&#x27;intelligence artificielle" in contenu or (
        "Aucun connecteur d'intelligence artificielle" in contenu
    )
