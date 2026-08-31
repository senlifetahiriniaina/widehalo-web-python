"""Crawler generique : parcourt EN GET toutes les URLs web navigables sans
parametre (listes, tableaux de bord, hubs de configuration, ecrans de
rapports...) et verifie qu'aucune ne renvoie 404/500.

Motivation directe (demande explicite de l'utilisateur) : avec ~200 ecrans
repartis sur ~20 modules, un clic manuel ecran par ecran ne passe pas a
l'echelle et un ecran cassE/disparu (ex. `/mfa/`, jamais construit, cf.
`apps/core/tests/test_mfa_web.py`) peut rester invisible longtemps. Ce test
n'est PAS un remplacement des tests fonctionnels par module deja existants
(`apps/*/tests/test_*_screens.py`, tests e2e Playwright) — il ne verifie
que la joignabilite structurelle (le squelette de la page se rend sans
lever d'exception), jamais le contenu metier d'un ecran precis. Les deux
sont complementaires : celui-ci attrape une regression de squelette sur
N'IMPORTE quel ecran nouveau ou existant sans qu'il faille l'ajouter
explicitement a une liste ; les tests par module verifient le comportement
reel.

Limitation assumee et documentee : seules les URLs SANS parametre
obligatoire (`<...>` dans le pattern) sont parcourues — un ecran de detail
(ex. `/accounting/<uuid>/`) exige un objet reel et reste couvert par les
tests par module deja existants, pas par ce crawler generique."""

from __future__ import annotations

import pytest
from apps.core.models.regulatory import CountryDefaultsProfile
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.services.smart_defaults import apply_country_defaults
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver
from django_otp.oath import totp

pytestmark = pytest.mark.django_db

# Prefixes jamais parcourus par ce crawler generique :
# - /api/       : API JSON, hors perimetre d'un crawler HTML (schema deja
#                 couvert par Schemathesis, cf. tests/contract).
# - /admin/     : interface django-admin standard, hors perimetre applicatif.
# - /static/, /media/ : fichiers, pas des ecrans.
# - /mfa/, /login/, /logout/, /change-password/, /setup/ : parcours
#   d'authentification/amorcage deja testes explicitement ailleurs
#   (test_mfa_web.py, test_onboarding.py, test_auth.py) — leur etat depend
#   de la sequence exacte de la session, pas d'un simple GET isole.
EXCLUDED_PREFIXES = (
    "/api/",
    "/admin/",
    "/static/",
    "/media/",
    "/mfa/",
    "/login/",
    "/logout/",
    "/change-password/",
    "/setup/",
)

# Noms d'URL exclus individuellement (pas de prefixe generique possible) :
# ecrans de TELECHARGEMENT de rapport (accounting/crm) qui exigent un ou
# plusieurs PARAMETRES DE REQUETE obligatoires (`?fiscal_year_id=...`,
# `?account_id=...`, `?journal_id=...`, `?pipeline_id=...`) resolus via
# `get_object_or_404(..., id=request.GET.get(...))` — l'equivalent d'un
# parametre de CHEMIN obligatoire (deja exclu par `_walk_url_patterns`),
# mais exprime en query string, donc invisible a l'heuristique base sur le
# pattern d'URL seul. Un GET nu renvoie 404 par CONCEPTION (get_object_or_404
# sur id=None), pas une panne — verifie explicitement (grep sur tout
# `apps/*/views_reports.py`) qu'aucun autre endpoint ne partage cette forme
# avant d'exclure UNIQUEMENT ces 5-la, jamais un assouplissement generique
# de HEALTHY_STATUSES qui masquerait une vraie route manquante.
EXCLUDED_NAMES = {
    "report_trial_balance",
    "report_general_ledger",
    "report_journal",
    "report_pipeline",
    "report_conversion",
}

# Statuts consideres SAINS pour un GET generique sans contexte metier
# specifique : 200 (rendu), 302 (redirection legitime, ex. vers un
# sous-ecran ou hors-perimetre du role de test), 403 (RBAC refuse
# l'acces — un refus explicite est un comportement SAIN, pas une panne),
# 405 (endpoint qui n'accepte que POST — l'existence de la route est ce
# qui compte ici, pas la methode). 404/500 restent seuls disqualifiants.
HEALTHY_STATUSES = {200, 302, 403, 405}


def _walk_url_patterns() -> list[tuple[str, str]]:
    """Retourne les couples (nom, chemin) de toutes les URLs web (hors
    prefixes exclus) qui ne comportent aucun parametre obligatoire."""
    resolver = get_resolver()
    found: list[tuple[str, str]] = []

    def walk(node: URLResolver, prefix: str) -> None:
        for entry in node.url_patterns:
            if isinstance(entry, URLPattern):
                path = prefix + str(entry.pattern)
                if entry.name is None or "<" in path:
                    continue
                if any(path.startswith(p.lstrip("/")) for p in EXCLUDED_PREFIXES):
                    continue
                if entry.name in EXCLUDED_NAMES:
                    continue
                found.append((entry.name, "/" + path))
            elif isinstance(entry, URLResolver):
                walk(entry, prefix + str(entry.pattern))

    walk(resolver, "")
    return found


@pytest.fixture
def admin_client() -> Client:
    """Client de session web authentifie, MFA verifiee, rattache a un
    tenant reel avec les SmartDefaults Madagascar deja appliques — le role
    `admin` a le perimetre RBAC le plus large (cf. `rbac_policy.py`), donc
    le moins de faux-positifs 403 dus au role plutot qu'a une vraie panne."""
    tenant = Tenant.objects.create(code="SMOKE-TEST", name="Smoke test")
    country_choices = CountryDefaultsProfile.objects.filter(country_code="MG")
    if country_choices.exists():
        apply_country_defaults(tenant, "MG")

    user = User.objects.create_user(email="smoke-admin@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)
    UserTenantMembership.objects.create(user=user, tenant=tenant, is_default=True)

    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content

    # Complete l'enrolement MFA (role `admin` soumis a MFA obligatoire,
    # cf. settings.CORE_MFA_REQUIRED_ROLES) — memes primitives que
    # apps/core/tests/test_mfa_web.py.
    client.get("/mfa/")
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content

    return client


ZERO_ARG_PAGES = _walk_url_patterns()


@pytest.mark.parametrize("name,path", ZERO_ARG_PAGES, ids=[f"{n}:{p}" for n, p in ZERO_ARG_PAGES])
def test_page_is_reachable(admin_client: Client, name: str, path: str) -> None:
    response = admin_client.get(path)
    assert response.status_code in HEALTHY_STATUSES, (
        f"{name} ({path}) returned {response.status_code}, expected one of "
        f"{sorted(HEALTHY_STATUSES)}"
    )


def test_crawler_found_a_meaningful_number_of_pages() -> None:
    """Garde-fou anti-regression du crawler lui-meme : si ce nombre chute
    brutalement, c'est que `_walk_url_patterns()` (ou une exclusion trop
    large) a casse la decouverte, pas que l'application a perdu des
    ecrans — a ajuster consciemment si le perimetre change reellement."""
    assert len(ZERO_ARG_PAGES) >= 100
