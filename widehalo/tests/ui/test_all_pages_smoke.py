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
from apps.core.tests.utils import grant_role
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

# Exclusions par CHEMIN, jamais par nom — et c'est une mesure, pas une
# preference : `risk_create` et `template_create` existent CHACUN DEUX FOIS
# dans le depot (`core`/`strategy` et `catalog`/`whatsapp`). Exclure par nom
# emporterait la route homonyme qui, elle, se rend parfaitement, et le
# crawler perdrait une couverture sans que personne ne le voie.
#
# Les 26 chemins ci-dessous repondaient DEJA 403 avant C-1 ; ils etaient
# simplement invisibles tant que `403` figurait dans HEALTHY_STATUSES.
# Les retirer du parcours ne masque donc aucune regression nouvelle : cela
# rend explicite ce que l'ancien jeu de statuts rendait muet.

# 1. Un GET n'a rien a y faire : l'idiome fusionne du depot, ~40 occurrences,
#    s'ecrit `if request.method != "POST" or not request.user.has_perm(...)`
#    et rend donc 403 pour une MAUVAISE METHODE la ou la convention de ce
#    crawler dit 405 (« l'existence de la route est ce qui compte, pas la
#    methode »). Ce crawler ne fait que des GET : ces routes n'ont pas de GET
#    a eprouver. Le jour ou l'idiome sera dissocie — mauvaise methode 405,
#    droit manquant 403 — elles reviennent au parcours sans rien changer ici.
ROUTES_POST_SEULEMENT = frozenset(
    {
        "/analytics/metrics/save/",
        "/analytics/refresh/",
        "/forecast/calendrier/ajouter/",
        "/forecast/calendrier/retirer/",
        "/forecast/publish/",
        "/pos/sale/open-session/",
        "/pos/sale/submit/",
        "/simulation/baseline/refresh/",
        "/stocks/scan/putaway/",
        "/stocks/scan/receive/",
        "/strategy/pilotage/budgets/new/",
        "/strategy/pilotage/initiatives/new/",
        "/strategy/pilotage/review-packs/new/",
        "/strategy/pilotage/risks/new/",
        "/whatsapp/config/cost-cap/",
        "/whatsapp/config/phone-number/",
        "/whatsapp/config/recipient-limit/",
        "/whatsapp/consent/grant/",
        "/whatsapp/consent/revoke/",
        "/whatsapp/messages/retry/",
        "/whatsapp/send/",
        "/whatsapp/templates/new/",
    }
)

# 2. Ecrans reserves au SUPERUTILISATEUR (`request.user.is_superuser`), que
#    l'utilisateur de ce crawler n'est deliberement pas.
#
#    **C'est un choix, et l'inverse serait un piege.** Faire du crawler un
#    superutilisateur ferait passer ces quatre ecrans — et rendrait `has_perm`
#    vrai pour TOUTE permission, donc le crawler traverserait sans rien
#    prouver la totalite des gardes RBAC qu'il doit desormais eprouver. On
#    garde un ROLE reel (`admin`, cf. la fixture) et on exclut ces quatre-la.
ROUTES_SUPERUTILISATEUR = frozenset(
    {
        "/backups/",
        "/backups/reset/",
        "/backups/schedule/",
        "/settings/scheduled-commands/",
    }
)

#: **L'idiome DISSOCIE, celui que le commentaire ci-dessus nomme comme
#: cible.** Une route qui n'accepte que POST le declare par `@require_POST`
#: et rend donc 405 — « methode non autorisee » —, pas 403 « droit
#: manquant ». Les deux ne disent pas la meme chose a qui debogue, et
#: confondre l'une avec l'autre est exactement ce que la note sur
#: `ROUTES_POST_SEULEMENT` deplore.
#:
#: Elles sont hors du parcours pour la meme raison que les autres — ce
#: crawler ne fait que des GET, et ces routes n'ont pas de GET a eprouver —
#: mais leur garde anti-cimetiere exige 405, jamais 403 : une route qui
#: retomberait dans l'idiome fusionne doit se voir.
ROUTES_POST_STRICTES = frozenset(
    {
        "/accounting/payments/payouts/announce/",
    }
)

EXCLUDED_PATHS = ROUTES_POST_SEULEMENT | ROUTES_SUPERUTILISATEUR | ROUTES_POST_STRICTES

# Statuts consideres SAINS pour un GET generique sans contexte metier
# specifique : 200 (rendu), 302 (redirection legitime, ex. vers un
# sous-ecran ou hors-perimetre du role de test), 405 (endpoint qui
# n'accepte que POST — l'existence de la route est ce qui compte ici, pas
# la methode). 404/500 restent disqualifiants.
#
# **403 EN A ETE RETIRE par C-1, et c'est la moitie du correctif.** Il y
# figurait avec le motif « un refus explicite est un comportement SAIN » —
# vrai en soi, ruineux ici. Combine au second defaut (la fixture
# ci-dessous creait un groupe `admin` SANS AUCUNE permission), il rendait
# ce crawler incapable de distinguer « la page se rend » de « la page
# refuse tout le monde » : les ~45 pages de crm/sales/accounting/
# logistics auraient bascule en 403 des la premiere garde de C-1 et ce
# test serait reste VERT, en n'affirmant plus que « la route existe ».
# Un crawler qui accepte le refus ne mesure plus rien.
#
# Consequence assumee : un ecran legitimement interdit au role de test
# doit desormais etre soit accessible a `admin` (cas normal — la matrice
# lui donne les 4 modules en view/add/change), soit inscrit dans
# EXCLUDED_NAMES avec son motif ecrit.
HEALTHY_STATUSES = {200, 302, 405}


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
                if "/" + path in EXCLUDED_PATHS:
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
    # `Group.objects.get_or_create(name="admin")` NE SUFFIT PAS, et c'est
    # l'autre moitie du correctif de C-1 : il cree un groupe portant le NOM
    # du role et AUCUNE permission Django. Verifie : il n'existe aucun
    # `conftest.py` racine, aucune migration ne seme de `Group`, et les
    # seuls appelants de `sync_group_permissions` sont les commandes de
    # semis et `apps/core/tests/utils.py`. Cet utilisateur s'appelait donc
    # `admin` avec `has_perm("crm.view_crmlead") is False`. `grant_role`
    # synchronise reellement les permissions depuis `ROLE_APP_PERMISSIONS`.
    grant_role(user, "admin")
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


def _tous_les_chemins_routes() -> set[str]:
    """Tous les chemins sans parametre, exclusions COMPRISES — la liste de
    reference contre laquelle verifier que les exclusions designent encore
    quelque chose."""
    chemins: set[str] = set()

    def walk(node: URLResolver, prefix: str) -> None:
        for entry in node.url_patterns:
            if isinstance(entry, URLPattern):
                path = prefix + str(entry.pattern)
                if entry.name is not None and "<" not in path:
                    chemins.add("/" + path)
            elif isinstance(entry, URLResolver):
                walk(entry, prefix + str(entry.pattern))

    walk(get_resolver(), "")
    return chemins


def test_the_exclusion_lists_never_become_a_graveyard() -> None:
    """Une exclusion qui ne designe plus rien endort la garde.

    Meme discipline que `DETTE_CONNUE` dans
    `tests/architecture/test_every_screen_is_reachable.py` : on n'ajoute
    pas a une liste d'exclusions sans que quelque chose empeche d'y
    laisser des entrees perimees. Une route renommee ou supprimee doit
    sortir d'ici, sinon la liste grossit et plus personne ne sait ce
    qu'elle protege."""
    routes = _tous_les_chemins_routes()
    perimes = sorted(EXCLUDED_PATHS - routes)
    assert not perimes, (
        f"Ces chemins exclus ne designent plus aucune route : {perimes}. "
        f"Route renommee ou supprimee — retirez-les de "
        f"ROUTES_POST_SEULEMENT / ROUTES_SUPERUTILISATEUR."
    )


def test_post_only_routes_still_refuse_a_get(admin_client: Client) -> None:
    """L'autre moitie de la discipline : une exclusion doit RESTER
    justifiee.

    Ces chemins sont hors du parcours parce qu'un GET y recoit 403 du fait
    de l'idiome fusionne methode+droit. Le jour ou cet idiome sera
    dissocie, ils rendront 405 (ou 200) et devront revenir dans le
    parcours. Sans ce test, ils resteraient exclus pour toujours et la
    couverture perdue ne serait jamais reprise."""
    revenus = sorted(
        chemin for chemin in ROUTES_POST_SEULEMENT if admin_client.get(chemin).status_code != 403
    )
    assert not revenus, (
        f"Ces chemins ne repondent plus 403 a un GET : {revenus}. L'idiome "
        f"fusionne a ete dissocie — retirez-les de ROUTES_POST_SEULEMENT "
        f"pour qu'ils reviennent dans le parcours du crawler."
    )


def test_les_routes_post_strictes_repondent_bien_405(admin_client) -> None:
    """Meme garde anti-cimetiere, pour l'idiome dissocie.

    Une route `@require_POST` doit rendre 405 a un GET. Si elle rend 403,
    elle a rejoint l'idiome fusionne et ment sur la raison du refus ; si
    elle rend 200, elle accepte desormais un GET et doit revenir dans le
    parcours du crawler. Les deux cas doivent se voir."""
    ecarts = sorted(
        f"{chemin} -> {admin_client.get(chemin).status_code}"
        for chemin in ROUTES_POST_STRICTES
        if admin_client.get(chemin).status_code != 405
    )
    assert not ecarts, (
        f"Ces chemins ne repondent plus 405 a un GET : {ecarts}. Soit ils ont "
        f"perdu leur `@require_POST`, soit ils acceptent un GET — dans le "
        f"second cas, retirez-les de ROUTES_POST_STRICTES."
    )


#: Les quatre modules que le lot C-1 dote d'une garde d'acces. Leur cas est
#: le seul ou ce crawler peut affirmer quelque chose de FORT : la matrice
#: donne `view/add/change` a `admin` sur les quatre (mesure directe de
#: `ROLE_APP_PERMISSIONS`), donc chacune de leurs pages DOIT se rendre.
MODULES_GARDES = ("/crm/", "/sales/", "/accounting/", "/logistics/")


def test_a_role_the_matrix_authorises_actually_gets_the_pages(admin_client: Client) -> None:
    """La garde qui donne son sens au reste du fichier.

    Un plancher global — « au moins N pages en 200 » — ne mord pas : sur
    256 pages parcourues, la grande majorite ne porte AUCUNE garde, si
    bien qu'un utilisateur totalement depourvu de droits en obtiendrait
    encore la quasi-totalite. Mesure faite, et falsification F94 a
    l'appui : le plancher passait avec un utilisateur sans une seule
    permission. Un test qui passe quand la propriete est fausse ne
    protege rien.

    La propriete VRAIMENT en jeu est plus etroite et verifiable : sur les
    quatre modules que C-1 garde, `admin` detient `view/add/change` par la
    matrice — donc **aucune** de leurs pages ne doit lui etre refusee. Ce
    test tombe des qu'une garde est trop large, qu'un codename est errone,
    ou que la fixture cesse d'accorder les permissions du role."""
    refusees = []
    for _nom, chemin in ZERO_ARG_PAGES:
        if not chemin.startswith(MODULES_GARDES):
            continue
        code = admin_client.get(chemin).status_code
        if code != 200:
            refusees.append(f"{chemin} -> {code}")
    assert not refusees, (
        f"Ces pages sont refusees a un utilisateur portant le role `admin`, alors que "
        f"ROLE_APP_PERMISSIONS lui donne view/add/change sur les quatre modules : "
        f"{sorted(refusees)}. Une garde trop large, un codename errone, ou une fixture "
        f"qui n'accorde plus les permissions du role."
    )


def test_the_guarded_modules_are_actually_crawled() -> None:
    """Auto-test de la garde precedente : si le parcours cessait de voir
    ces modules, elle passerait sur zero page et declarerait tout sain.

    C'est la panne silencieuse de cette famille de gardes, deja rencontree
    trois fois dans cette vague."""
    comptes = {
        prefixe: sum(1 for _n, c in ZERO_ARG_PAGES if c.startswith(prefixe))
        for prefixe in MODULES_GARDES
    }
    vides = sorted(prefixe for prefixe, n in comptes.items() if n == 0)
    assert not vides, (
        f"Le parcours ne contient plus aucune page pour {vides} : c'est le crawler "
        f"qui est casse, pas le depot qui a maigri. Mesure a C-1 : {comptes}."
    )


def test_crawler_found_a_meaningful_number_of_pages() -> None:
    """Garde-fou anti-regression du crawler lui-meme : si ce nombre chute
    brutalement, c'est que `_walk_url_patterns()` (ou une exclusion trop
    large) a casse la decouverte, pas que l'application a perdu des
    ecrans — a ajuster consciemment si le perimetre change reellement."""
    assert len(ZERO_ARG_PAGES) >= 100
