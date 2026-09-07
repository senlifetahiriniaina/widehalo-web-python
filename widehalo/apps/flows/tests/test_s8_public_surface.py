"""S8, bloc B — la surface publique déclarée, documentée, et son bac à
sable.

**API-2** : « aucune opération non déclarée dans la liste blanche publique
n'est atteignable par un jeton client, même si l'endpoint interne existe. »
La partie structurelle est tenue par
`tests/architecture/test_public_surface_is_declared.py` — chaque route
publique porte son décorateur, et la correspondance route ↔ opération tient
dans les deux sens. Ce fichier tient ce qu'une garde statique ne peut pas
voir : le comportement.

**Le bac à sable n'a demandé aucun mécanisme nouveau, et c'est le résultat
qui compte.** « Environnement d'essai avec jeu de données isolé » : le
clonage de société existe depuis la Phase 1
(`core.services.sandbox.clone_tenant_to_sandbox`), et une clé désigne sa
société. Un bac à sable est donc une clé émise sur une société clonée —
rien de plus. La vérification qui importe est qu'elle ne voie RIEN de la
société d'origine, et c'est la RLS qui le garantit, pas un réglage.
"""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sandbox import clone_tenant_to_sandbox
from apps.core.tests.utils import grant_role, use_tenant
from apps.flows.api_public import OPERATION_EXCHANGES_READ
from apps.flows.models import FlwLink
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.public_operations import PublicOperation, list_public_operations
from apps.flows.services import api_keys
from apps.flows.services.exchange import prepare_exchange
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db

_URL = "/api/public/v1/exchanges"


@pytest.fixture(autouse=True)
def compteur_propre():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _appel(clair: str, url: str = _URL):
    from django.test import Client

    return Client().get(url, HTTP_AUTHORIZATION=f"Bearer {clair}")


@pytest.fixture
def societe_et_cle():
    societe = Tenant.objects.create(code="S8-PROD", name="Production SARL")
    utilisateur = User.objects.create_user(email="s8@example.com", password="Str0ngPassw0rd!23")
    grant_role(utilisateur, "admin")
    with use_tenant(societe.id):
        liaison = FlwLinkFactory(tenant=societe, state=FlwLink.STATE_ACTIVE)
        prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body='{"prod": 1}')
        _objet, clair = api_keys.issue_key(
            societe, utilisateur, label="Production", scopes=[OPERATION_EXCHANGES_READ]
        )
    return societe, utilisateur, clair


# --- API-2, côté comportement ---------------------------------------------------


def test_an_internal_endpoint_is_unreachable_on_the_public_surface(societe_et_cle) -> None:
    """« Même si l'endpoint interne existe. » Les deux surfaces sont montées
    sous deux préfixes distincts : un chemin interne demandé sous
    `/api/public/` n'existe pas, il ne se contente pas d'être refusé."""
    _societe, _utilisateur, clair = societe_et_cle
    reponse = _appel(clair, "/api/public/v1/approvals/pending")
    assert reponse.status_code == 404


def test_the_public_schema_is_published_and_separate() -> None:
    """« Surface REST versionnée, décrite en OpenAPI et publiée. » Publiée
    SÉPARÉMENT : un intégrateur qui lirait le schéma interne y verrait des
    centaines d'opérations qu'il ne peut pas appeler, et prendrait notre
    structure interne pour un contrat."""
    from django.test import Client

    public = Client().get("/api/public/v1/openapi.json")
    assert public.status_code == 200
    schema = public.json()
    assert schema["info"]["version"] == "public-v1"
    chemins = set(schema["paths"])
    assert "/api/public/v1/exchanges" in chemins
    assert not any("/approvals" in chemin for chemin in chemins), (
        "Le schéma public expose des chemins internes : les deux surfaces se sont mélangées."
    )


def test_the_public_schema_describes_what_the_integrator_needs() -> None:
    """Un schéma sans description est un schéma qu'il faut nous demander
    d'expliquer — ce qui annule l'intérêt d'une API publique."""
    from django.test import Client

    schema = Client().get("/api/public/v1/openapi.json").json()
    assert schema["info"].get("description")
    assert "Bearer" in schema["info"]["description"]


# --- Le bac à sable --------------------------------------------------------------


def test_a_sandbox_key_sees_the_sandbox_and_never_production(societe_et_cle) -> None:
    """« Environnement d'essai avec jeu de données ISOLÉ. » L'isolation
    n'est pas un réglage de l'API : c'est la même Row-Level Security que
    partout ailleurs, et c'est pourquoi elle est fiable — un bac à sable
    protégé par un `if` dans la couche API tomberait au premier oubli."""
    societe, utilisateur, clair_prod = societe_et_cle
    from apps.flows.models import FlwExchange

    with use_tenant(societe.id):
        id_production = str(FlwExchange.objects.first().id)

    bac = clone_tenant_to_sandbox(societe)
    with use_tenant(bac.id):
        liaison = FlwLinkFactory(tenant=bac, state=FlwLink.STATE_ACTIVE)
        essai = prepare_exchange(bac, liaison, operation=OP_PUSH_DOCUMENT, body='{"essai": 1}')
        _objet, clair_bac = api_keys.issue_key(
            bac, utilisateur, label="Bac à sable", scopes=[OPERATION_EXCHANGES_READ]
        )

    vus_du_bac = {ligne["id"] for ligne in _appel(clair_bac).json()["results"]}
    vus_de_production = {ligne["id"] for ligne in _appel(clair_prod).json()["results"]}

    # **Le clonage RECOPIE les données**, et c'est son objet : un bac à sable
    # vide ne servirait à rien pour essayer une configuration. Ce qui doit
    # être vrai n'est donc pas « le bac ne voit qu'une ligne » — le premier
    # jet de ce test l'affirmait et rougissait pour cette raison — mais que
    # les IDENTITÉS ne se croisent jamais : la copie porte un identifiant
    # neuf (`object_remap`), et rien de ce qui naît dans le bac n'apparaît
    # en production.
    assert str(essai.id) in vus_du_bac
    assert id_production not in vus_du_bac, (
        "Le bac à sable voit la LIGNE de production, pas sa copie : le "
        "remappage d'identifiants n'a pas eu lieu."
    )
    assert str(essai.id) not in vus_de_production, (
        "Un échange né dans le bac à sable apparaît en production : le jeu "
        "de données n'est pas isolé."
    )
    assert id_production in vus_de_production, "Témoin : la production voit les siens."


def test_a_production_key_never_sees_the_sandbox(societe_et_cle) -> None:
    """Le témoin, et il n'est pas symétrique du précédent par hasard : un
    bac à sable qui verrait la production est une fuite de données ; une
    production qui verrait le bac à sable est un rapport faux. Les deux
    comptent."""
    societe, _utilisateur, clair = societe_et_cle
    avant = len(_appel(clair).json()["results"])
    bac = clone_tenant_to_sandbox(societe)
    with use_tenant(bac.id):
        liaison = FlwLinkFactory(tenant=bac, state=FlwLink.STATE_ACTIVE)
        prepare_exchange(bac, liaison, operation=OP_PUSH_DOCUMENT, body='{"essai": 2}')

    assert len(_appel(clair).json()["results"]) == avant


def test_a_sandbox_is_marked_as_such_and_expires(societe_et_cle) -> None:
    """Un bac à sable sans date de fin devient une seconde production, et
    la purge de `core.sandbox` existe précisément pour l'empêcher."""
    societe, _utilisateur, _clair = societe_et_cle
    bac = clone_tenant_to_sandbox(societe)
    assert bac.is_sandbox is True
    assert bac.sandbox_expires_at is not None
    assert bac.sandbox_source_id == societe.id


# --- La politique de dépréciation ------------------------------------------------


def test_a_deprecation_without_an_end_date_is_refused() -> None:
    """« Une opération publiée ne se retire plus, elle se déprécie sur
    plusieurs versions. » Déprécier sans annoncer de fin laisse un
    intégrateur sans échéance ; annoncer une fin sans avoir déprécié le
    prend par surprise. Les deux dates vont ensemble ou pas du tout."""
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        PublicOperation(
            code="x.y", label="X", permission="core.view_user", deprecated_since="2027-01-01"
        )
    with pytest.raises(ValidationError):
        PublicOperation(code="x.y", label="X", permission="core.view_user", sunset_on="2028-01-01")
    # Les deux, ou aucune.
    PublicOperation(
        code="x.y",
        label="X",
        permission="core.view_user",
        deprecated_since="2027-01-01",
        sunset_on="2028-01-01",
    )
    PublicOperation(code="x.y", label="X", permission="core.view_user")


def test_no_operation_is_deprecated_yet_and_that_is_said(societe_et_cle) -> None:
    """L'état réel, constaté plutôt que supposé. Le mécanisme existe et est
    testé ; aucune opération ne l'utilise encore, parce que la surface vient
    d'ouvrir. Ce test rougira le jour où la première dépréciation arrivera,
    et ce sera le rappel de vérifier que ses en-têtes partent bien."""
    depreciees = [op.code for op in list_public_operations() if op.is_deprecated]
    assert depreciees == [], (
        f"Première opération dépréciée : {depreciees}. Vérifier que les en-têtes "
        "`Deprecation` et `Sunset` arrivent bien au client."
    )
    _societe, _utilisateur, clair = societe_et_cle
    reponse = _appel(clair)
    assert "Deprecation" not in reponse
    assert "Sunset" not in reponse
