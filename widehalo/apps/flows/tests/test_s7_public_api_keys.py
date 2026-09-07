"""S7, bloc B — clés publiques : portées, débit, expiration, révocation.

Trois critères. **API-1** : « un jeton client ne peut obtenir aucune donnée
qu'un utilisateur du rôle correspondant ne pourrait consulter dans
l'interface ». **API-6** : « la révocation d'une clé est effective
immédiatement, y compris pour les appels en cours d'authentification ».
**API-7** : « le dépassement du débit d'une clé produit une réponse
normalisée avec délai d'attente indiqué, et n'affecte ni les autres clés du
tenant ni les autres tenants ».

**Ce qui existait, et ce qui manquait.** L'audit relevait qu'il n'existait
« aucune notion de jeton client : recherche exhaustive sur `ApiKey` /
`api_key` / `access_token` dans `apps/core/models/` → zéro résultat ».
`apps/core/throttling.py` existait mais **n'était appliqué à aucun
endpoint** — son seul usage était un test — et ne connaissait ni clé ni
société.

**Comment API-1 est tenu, et pourquoi ce n'est pas un raccourci.** La clé
porte un UTILISATEUR réel, dont les groupes décident. L'alternative aurait
été de recopier la matrice de droits dans un second mécanisme propre à
l'API — qui aurait divergé au premier rôle ajouté. Le cahier tranche
lui-même : « le contrôle est celui de la Phase 1 pour le copilote, réutilisé
SANS MODIFICATION ».
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.flows.api_public import OPERATION_EXCHANGES_READ
from apps.flows.models import FlwApiKey, FlwExchange, FlwLink
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.public_operations import (
    PublicOperation,
    list_public_operations,
    public_operation_codes,
    register_public_operation,
    validate_scopes,
)
from apps.flows.services import api_keys
from apps.flows.services.exchange import prepare_exchange
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db

_URL = "/api/public/v1/exchanges"


@pytest.fixture(autouse=True)
def compteur_propre():
    """Le débit vit dans le cache, qui est un global de processus. Sans
    remise à zéro, l'ordre des tests déciderait de leur résultat — le même
    piège qu'un registre d'adaptateurs qui fuite."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S7-API", name="Intégrateur SARL")


@pytest.fixture
def cle(societe):
    """Une clé émise pour un compte de service au rôle `admin`, portant la
    seule opération publique déclarée."""
    utilisateur = User.objects.create_user(
        email="service@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(utilisateur, "admin")
    with use_tenant(societe.id):
        objet, clair = api_keys.issue_key(
            societe,
            utilisateur,
            label="Intégration comptable",
            scopes=[OPERATION_EXCHANGES_READ],
        )
        liaison = FlwLinkFactory(tenant=societe, state=FlwLink.STATE_ACTIVE)
        prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body='{"a": 1}')
    return objet, clair, utilisateur


def _appel(clair: str, url: str = _URL):
    return Client().get(url, HTTP_AUTHORIZATION=f"Bearer {clair}")


# --- Le chemin nominal, d'abord ------------------------------------------------


def test_a_valid_key_reads_its_own_company_s_exchanges(cle) -> None:
    """**Le témoin, et il ouvre le fichier.** Tous les tests qui suivent
    affirment un refus ; sans une réussite constatée, une surface publique
    entièrement cassée les rendrait tous verts."""
    _objet, clair, _utilisateur = cle
    reponse = _appel(clair)
    assert reponse.status_code == 200, reponse.content
    resultats = reponse.json()["results"]
    assert len(resultats) == 1
    assert resultats[0]["operation"] == OP_PUSH_DOCUMENT


def test_the_key_designates_its_company_without_any_header(cle, societe) -> None:
    """Un client public n'envoie pas de `X-Tenant-Id` : il n'a pas à
    connaître nos identifiants internes, et le laisser en choisir un
    reviendrait à le laisser choisir la société dans laquelle on cherche sa
    clé. C'est le résolveur déclaré à `core.services.tenant_resolvers` qui
    la pose — donc par le même chemin que le middleware depuis la Phase 1,
    donc avec `SET LOCAL app.tenant_id`, donc avec la RLS."""
    _objet, clair, _utilisateur = cle
    autre = Tenant.objects.create(code="S7-AUTRE", name="Autre SARL")
    with use_tenant(autre.id):
        liaison = FlwLinkFactory(tenant=autre, state=FlwLink.STATE_ACTIVE)
        prepare_exchange(autre, liaison, operation=OP_PUSH_DOCUMENT, body='{"b": 2}')

    reponse = _appel(clair)
    assert reponse.status_code == 200
    assert len(reponse.json()["results"]) == 1, (
        "La clé a vu les échanges d'une autre société : le résolveur n'a pas "
        "posé la bonne, ou la RLS ne s'applique pas."
    )


def test_a_stolen_key_opens_nothing_on_the_internal_surface(cle) -> None:
    """Deux surfaces séparées ne servent à rien si un jeton de l'une ouvre
    l'autre. Le résolveur ne regarde que `/api/public/`, et la surface
    interne n'accepte que le JWT."""
    _objet, clair, _utilisateur = cle
    reponse = Client().get("/api/v1/approvals/pending", HTTP_AUTHORIZATION=f"Bearer {clair}")
    assert reponse.status_code == 401, reponse.content


# --- API-1 : aucune élévation par l'API ----------------------------------------


def test_a_key_never_obtains_what_its_user_could_not_see(societe) -> None:
    """Le test que le critère décrit mot pour mot : « un jeton de portée
    commerciale interrogeant des données comptables ». La clé porte un
    utilisateur au rôle `commercial`, qui n'a pas `flows.view_flwexchange`
    — la portée ne peut donc pas le lui donner."""
    commercial = User.objects.create_user(
        email="commercial@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(commercial, "commercial")
    with use_tenant(societe.id):
        _objet, clair = api_keys.issue_key(
            societe, commercial, label="Commerciale", scopes=[OPERATION_EXCHANGES_READ]
        )
    reponse = _appel(clair)
    assert reponse.status_code in (403, 401), (
        "Un jeton commercial a obtenu le journal d'échanges : la portée a "
        "élevé les droits de son porteur, ce qu'API-1 interdit."
    )


def test_a_scope_the_key_does_not_carry_is_refused(societe) -> None:
    """Deny-by-default : une portée vide n'autorise RIEN. L'inverse — vide
    veut dire tout — transforme un oubli de saisie en clé universelle."""
    utilisateur = User.objects.create_user(email="sans@example.com", password="Str0ngPassw0rd!23")
    grant_role(utilisateur, "admin")
    with use_tenant(societe.id):
        _objet, clair = api_keys.issue_key(societe, utilisateur, label="Sans portée", scopes=[])
    reponse = _appel(clair)
    assert reponse.status_code == 403
    assert OPERATION_EXCHANGES_READ in reponse.json()["detail"], (
        "Le message doit NOMMER l'opération manquante : sans cela, un "
        "intégrateur qui a vingt portées doit deviner laquelle manque."
    )


def test_an_undeclared_scope_is_refused_at_registration(societe) -> None:
    """« Portées exprimées en opérations publiques DÉCLARÉES, jamais en
    tables » (§13.2). Une portée qui nommerait n'importe quoi laisserait
    croire à un droit inexistant — et le jour où l'opération serait
    déclarée, le jeton l'obtiendrait sans que personne ne l'ait décidé."""
    from django.core.exceptions import ValidationError

    utilisateur = User.objects.create_user(email="x@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(societe.id), pytest.raises(ValidationError):
        api_keys.issue_key(societe, utilisateur, label="Fantôme", scopes=["comptabilite.tout"])


# --- API-6 : révocation immédiate ----------------------------------------------


def test_revocation_is_effective_on_the_very_next_call(cle) -> None:
    """« Effective immédiatement, y compris pour les appels en cours
    d'authentification. » C'est la lecture stricte qui interdit tout cache :
    un cache d'une seconde suffirait à laisser passer l'appel qu'on cherche
    justement à arrêter."""
    objet, clair, _utilisateur = cle
    assert _appel(clair).status_code == 200, "Témoin : la clé fonctionnait avant."

    with use_tenant(objet.tenant_id):
        api_keys.revoke(objet, reason="clé publiée par erreur")

    assert _appel(clair).status_code == 401


def test_revoking_twice_keeps_the_first_date(cle) -> None:
    """Écraser la date d'une révocation effacerait le seul élément qui
    permette de dire si un appel était légitime au moment où il a eu lieu."""
    objet, _clair, _utilisateur = cle
    with use_tenant(objet.tenant_id):
        api_keys.revoke(objet, reason="première")
        premiere = objet.revoked_at
        api_keys.revoke(objet, reason="seconde")
        objet.refresh_from_db()
    assert objet.revoked_at == premiere
    assert objet.revoked_reason == "première"


def test_an_expired_key_opens_nothing(societe) -> None:
    utilisateur = User.objects.create_user(email="exp@example.com", password="Str0ngPassw0rd!23")
    grant_role(utilisateur, "admin")
    with use_tenant(societe.id):
        _objet, clair = api_keys.issue_key(
            societe,
            utilisateur,
            label="Expirée",
            scopes=[OPERATION_EXCHANGES_READ],
            expires_at=timezone.now() - dt.timedelta(seconds=1),
        )
    assert _appel(clair).status_code == 401


def test_the_three_refusals_are_indistinguishable_from_outside(societe, cle) -> None:
    """Inconnue, révoquée, expirée : le même 401, sans motif. Dire à un
    appelant que sa clé « existe mais est expirée » lui apprend qu'elle
    existe."""
    objet, _clair, _utilisateur = cle
    with use_tenant(objet.tenant_id):
        api_keys.revoke(objet)
    inconnue = _appel("wh_jamais_emise")
    revoquee = _appel(_clair)
    assert inconnue.status_code == revoquee.status_code == 401
    assert inconnue.content == revoquee.content


# --- API-7 : le débit, par clé --------------------------------------------------


def test_the_rate_limit_answers_with_a_wait_time(societe) -> None:
    """« Une réponse normalisée avec DÉLAI D'ATTENTE INDIQUÉ. » La
    limitation générique du produit (`core.throttling`) rend bien un 429
    normalisé, mais sans `Retry-After` — un client bien élevé n'a alors
    d'autre choix que de réessayer au hasard, ce qui aggrave exactement la
    situation qu'on borne."""
    utilisateur = User.objects.create_user(email="deb@example.com", password="Str0ngPassw0rd!23")
    grant_role(utilisateur, "admin")
    with use_tenant(societe.id):
        _objet, clair = api_keys.issue_key(
            societe,
            utilisateur,
            label="Débit serré",
            scopes=[OPERATION_EXCHANGES_READ],
            rate_limit_per_hour=2,
        )
    assert _appel(clair).status_code == 200
    assert _appel(clair).status_code == 200
    troisieme = _appel(clair)
    assert troisieme.status_code == 429
    assert troisieme["Retry-After"], "Aucun délai d'attente indiqué."
    assert troisieme["Content-Type"] == "application/problem+json"


def test_one_key_hitting_its_limit_never_penalises_another(societe) -> None:
    """« N'affecte ni les autres clés du tenant ni les autres tenants. »
    Deux clés d'un même intégrateur — l'une pour son bac à sable, l'autre
    pour sa production — ne doivent pas se pénaliser.

    **Les deux clés portent le MÊME plafond, et ce détail est le test.**
    La première version leur en donnait deux différents (1 et 10), et elle
    passait aussi bien avec un compteur indexé sur la société : le compte
    partagé valait 1, ce qui restait sous le plafond de 10 de la seconde
    clé. Falsification faite — remplacer `key.id` par `key.tenant_id` dans
    la clef du compteur — et le test restait vert. Un test qui survit à la
    mutation qu'il est censé attraper ne teste pas ce qu'il annonce.

    Avec le même plafond, un compteur partagé fait échouer la seconde clé
    au premier appel, et la mutation rougit."""
    utilisateur = User.objects.create_user(email="deux@example.com", password="Str0ngPassw0rd!23")
    grant_role(utilisateur, "admin")
    with use_tenant(societe.id):
        _a, clair_a = api_keys.issue_key(
            societe,
            utilisateur,
            label="Bac à sable",
            scopes=[OPERATION_EXCHANGES_READ],
            rate_limit_per_hour=1,
        )
        _b, clair_b = api_keys.issue_key(
            societe,
            utilisateur,
            label="Production",
            scopes=[OPERATION_EXCHANGES_READ],
            rate_limit_per_hour=1,
        )
    assert _appel(clair_a).status_code == 200
    assert _appel(clair_a).status_code == 429, "Témoin : la première clé atteint son plafond."
    assert _appel(clair_b).status_code == 200, (
        "La seconde clé est pénalisée par la première : le compteur est "
        "indexé sur la société ou sur l'utilisateur, pas sur la clé."
    )


# --- Le secret lui-même ---------------------------------------------------------


def test_the_plaintext_key_is_never_stored(cle) -> None:
    """Le clair n'existe qu'une fois. Une clé qu'on peut relire est une clé
    qu'un export, une sauvegarde ou une capture d'écran de support peut
    emporter — et le cahier range les identifiants de tiers parmi ce qui
    n'est « jamais exporté »."""
    objet, clair, _utilisateur = cle
    with use_tenant(objet.tenant_id):
        objet.refresh_from_db()
    assert clair not in objet.token_hash
    assert objet.token_hash == api_keys.fingerprint(clair)
    # Le préfixe affichable montre les six premiers caractères du SECRET,
    # jamais la société qui le sépare dans le jeton : elle n'apprend rien à
    # un exploitant qui regarde ses propres clés.
    # `secrets.token_urlsafe` produit des `_` : ne couper que sur le
    # PREMIER séparateur, comme `tenant_id_of` le fait avec `partition`.
    secret = clair.removeprefix(api_keys.TOKEN_PREFIX).partition("_")[2]
    assert objet.prefix == api_keys.TOKEN_PREFIX + secret[:6]
    assert len(objet.prefix) < len(secret) // 2, (
        "Le préfixe affichable est trop long : il réduirait utilement la recherche exhaustive."
    )


def test_a_token_presented_under_another_company_fails_closed(cle) -> None:
    """**Le défaut trouvé en écrivant ces tests, et il aurait été fatal en
    production.** `FlwApiKey` hérite de `BaseModel`, donc de la Row-Level
    Security : la policy n'expose une ligne que si `app.tenant_id` désigne
    sa société. Or l'authentification se produit AVANT que la société soit
    connue — c'est justement la clé qui la désigne. En début de requête,
    `app.tenant_id` est vide, la policy ne rend aucune ligne, et l'API
    publique n'aurait pu authentifier personne.

    Le test ne l'avait pas vu tout de suite : sous pytest, une transaction
    englobante fait survivre le `SET LOCAL` d'un `use_tenant` précédent, si
    bien que la policy laissait passer par accident. Deuxième faux positif
    de ce genre relevé dans ce dépôt.

    La société voyage donc DANS le jeton, en clair. Ce test vérifie que
    cela ne relâche rien : remplacer la société par une autre fait chercher
    l'empreinte sous cette société-là, où la policy la cache. Ça échoue, et
    ça échoue FERMÉ."""
    _objet, clair, _utilisateur = cle
    autre = Tenant.objects.create(code="S7-USURPE", name="Usurpateur SARL")
    # `secrets.token_urlsafe` produit des `_` : ne couper que sur le
    # PREMIER séparateur, comme `tenant_id_of` le fait avec `partition`.
    secret = clair.removeprefix(api_keys.TOKEN_PREFIX).partition("_")[2]
    usurpe = f"{api_keys.TOKEN_PREFIX}{autre.id.hex}_{secret}"

    assert _appel(clair).status_code == 200, "Témoin : le vrai jeton fonctionne."
    assert _appel(usurpe).status_code == 401


def test_a_malformed_token_is_refused_without_raising() -> None:
    """Le résolveur s'exécute dans le middleware, avant toute vue : une
    exception y transformerait un jeton mal recopié en panne générale."""
    for jeton in ["", "wh_", "wh_pas-un-uuid_secret", "sans-prefixe", "wh_" + "0" * 31 + "_x"]:
        assert _appel(jeton).status_code == 401
    assert api_keys.tenant_id_of("wh_pas-un-uuid_secret") is None
    assert api_keys.tenant_id_of("sans-prefixe") is None


def test_the_key_records_when_it_was_last_used(cle) -> None:
    """Sans cette date, personne ne peut répondre à « cette clé sert-elle
    encore ? » — et personne ne révoque jamais."""
    objet, clair, _utilisateur = cle
    with use_tenant(objet.tenant_id):
        objet.refresh_from_db()
        assert objet.last_used_at is None
    _appel(clair)
    with use_tenant(objet.tenant_id):
        objet.refresh_from_db()
    assert objet.last_used_at is not None


# --- Le registre d'opérations publiques ----------------------------------------


def test_the_public_operation_registry_is_populated() -> None:
    """Un registre vide rendrait tous les tests de portée verts par
    construction — le zéro qui ne prouve rien."""
    assert OPERATION_EXCHANGES_READ in public_operation_codes()
    assert list_public_operations()


def test_two_declarations_of_the_same_code_with_different_contracts_are_refused() -> None:
    """Deux modules qui publieraient le même nom pour deux contrats
    distincts rendraient la portée d'un jeton dépendante de l'ordre de
    chargement des applications."""
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        register_public_operation(
            PublicOperation(
                code=OPERATION_EXCHANGES_READ, label="Autre chose", permission="core.view_user"
            )
        )
    # Idempotence : la MÊME déclaration passe, pour que `ready()` puisse
    # tourner deux fois en développement.
    register_public_operation(
        PublicOperation(
            code=OPERATION_EXCHANGES_READ,
            label="Journal des échanges",
            permission="flows.view_flwexchange",
            description=(
                "Les échanges de la société, du plus récent au plus ancien. "
                "Le « journal d'appel consultable par le client » du cahier (§14.2)."
            ),
        )
    )


def test_a_duplicated_scope_is_refused() -> None:
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_scopes([OPERATION_EXCHANGES_READ, OPERATION_EXCHANGES_READ])
    with pytest.raises(ValidationError):
        validate_scopes("pas-une-liste")
    validate_scopes([OPERATION_EXCHANGES_READ])


def test_a_copied_company_never_inherits_a_working_key(societe) -> None:
    """Le champ s'appelle `token_hash` et pas `key_hash`, et c'est le
    registre `object_remap.SECRET_TOKEN_FIELD_NAMES` qui l'impose : sans ce
    nom exact, la copie d'une société recopierait l'empreinte telle quelle,
    et une sauvegarde restaurée ressusciterait une clé valide chez
    quelqu'un d'autre."""
    from apps.core.services.object_remap import (
        SECRET_TOKEN_FIELD_NAMES,
        regenerate_secret_token_fields,
    )

    assert "token_hash" in SECRET_TOKEN_FIELD_NAMES
    utilisateur = User.objects.create_user(email="cp@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(societe.id):
        objet, clair = api_keys.issue_key(
            societe, utilisateur, label="À copier", scopes=[OPERATION_EXCHANGES_READ]
        )
    avant = objet.token_hash
    regenerate_secret_token_fields(objet)
    assert objet.token_hash != avant
    assert objet.token_hash != api_keys.fingerprint(clair)


def test_the_exchange_journal_never_returns_a_payload(cle) -> None:
    """Rendre le contenu ferait de cette opération un canal d'exfiltration
    de pièces métier, avec une portée qui n'annonce qu'un journal."""
    _objet, clair, _utilisateur = cle
    ligne = _appel(clair).json()["results"][0]
    assert "payload_fingerprint" in ligne, "L'empreinte, elle, doit être là : c'est la preuve."
    assert "body" not in ligne
    assert "payload" not in ligne
    assert FlwExchange.objects.model is FlwExchange  # ancre de lecture


def test_the_key_model_is_under_row_level_security(societe, cle) -> None:
    """Une clé est un secret de société : la voir depuis une autre serait
    la même fuite que voir son échange."""
    objet, _clair, _utilisateur = cle
    autre = Tenant.objects.create(code="S7-RLS", name="Autre SARL")
    with use_tenant(autre.id):
        assert list(FlwApiKey.all_objects.filter(id=objet.id)) == []
