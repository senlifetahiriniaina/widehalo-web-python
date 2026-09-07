"""S6, FLX-7 — isolation à deux sociétés sur le hub de flux.

Le critère nomme QUATRE objets, et il faut les traiter un par un : « un test
d'isolation à deux tenants vérifie qu'aucun **échange**, **secret**,
**liaison** ou **charge utile** d'un tenant n'est atteignable depuis
l'autre, **y compris par identifiant direct** ».

**Zéro occurrence dans le dépôt avant ce sprint.** Le hub de flux existait
depuis six sprints avec ses cinq tables sous Row-Level Security, et pas une
ligne ne le vérifiait. Le motif de s'en soucier n'est pas théorique : le
même défaut a été trouvé la semaine dernière sur les validations
génériques — `ApprovalRule` n'héritait pas de `BaseModel` et un approbateur
d'une société pouvait valider les pièces d'une autre.

**Deux couches, et la seconde est la seule qui prouve quelque chose.** Le
`TenantManager` filtre côté Django ; la policy PostgreSQL filtre côté base.
Ne tester que la première laisserait passer une table oubliée par
`apply_rls`, et ne tester que par `objects` ne dirait rien de ce que voit un
`all_objects`, un `_base_manager` (donc `refresh_from_db`) ou une requête
brute. Les assertions qui portent sur la BASE passent donc toutes par
`all_objects`, qui ne filtre rien côté Django : seule la policy peut alors
rendre l'ensemble vide.

**« Par identifiant direct » n'est pas une clause décorative.** C'est
exactement la forme des services de rejeu — `replayable_exchanges(tenant,
ids=[...])`, `estimate_replay`, `replay_selection` prennent une liste
d'identifiants venue d'un écran. Un identifiant est devinable, recopiable
et parfois journalisé : c'est le chemin par lequel une fuite arrive, pas une
requête de liste.
"""

from __future__ import annotations

import pytest
from django.db import ProgrammingError, connection

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.adapters import reference
from apps.flows.models import (
    FlwCredential,
    FlwExchange,
    FlwLink,
    FlwPayload,
)
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.services import public as flows_public
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import drain_outbound_queue, process_outbound_queue
from apps.flows.services.replay import (
    estimate_replay,
    replay_selection,
    replayable_exchanges,
)
from apps.flows.tests.factories import (
    FlwConnectorFactory,
    FlwCredentialFactory,
    FlwLinkFactory,
)

pytestmark = pytest.mark.django_db

#: Les cinq tables du hub qui portent une donnée de société. Le catalogue
#: de connecteurs en fait partie : un connecteur est déclaré PAR société
#: (`uniq_flw_connector_code_per_tenant`), et savoir qu'une autre société a
#: enrôlé telle plateforme fiscale est déjà une information.
TABLES_DU_HUB = ("flw_connector", "flw_credential", "flw_link", "flw_exchange", "flw_payload")

_DOCUMENT = "facture_vente"
_CORPS = '{"montant": 42000, "client": "chez B"}'


@pytest.fixture
def deux_societes():
    """Deux sociétés, et TOUT le nécessaire chez la seconde.

    Les lignes de la société B sont créées SOUS SON CONTEXTE : depuis que
    la RLS est en `FORCE`, une insertion hors contexte est refusée par
    PostgreSQL lui-même — ce qui est le comportement voulu, et ce qui rend
    ce détail de fixture obligatoire plutôt que stylistique."""
    a = Tenant.objects.create(code="FLX7-A", name="Société A")
    b = Tenant.objects.create(code="FLX7-B", name="Société B")

    with use_tenant(b.id):
        connecteur_b = FlwConnectorFactory(tenant=b, code=reference.CONNECTOR_CODE)
        secret_b = FlwCredentialFactory(
            tenant=b, connector=connecteur_b, secret="cle-tres-secrete-de-B"
        )
        liaison_b = FlwLinkFactory(
            tenant=b, connector=connecteur_b, credential=secret_b, state=FlwLink.STATE_ACTIVE
        )
        document_id = _uuid()
        echange_b = prepare_exchange(
            b,
            liaison_b,
            operation=OP_PUSH_DOCUMENT,
            document_type=_DOCUMENT,
            document_id=document_id,
            body=_CORPS,
        )
        transition_exchange(echange_b, to_state=FlwExchange.STATE_QUEUED)
        charge_b = FlwPayload.objects.get(exchange=echange_b)

    return {
        "a": a,
        "b": b,
        "connecteur_b": connecteur_b,
        "secret_b": secret_b,
        "liaison_b": liaison_b,
        "echange_b": echange_b,
        "charge_b": charge_b,
        "document_id": document_id,
    }


def _uuid():
    import uuid

    return uuid.uuid4()


# --- Le témoin, d'abord --------------------------------------------------------


def test_company_b_really_sees_its_own_four_objects(deux_societes) -> None:
    """**Sans ce test, tous les suivants seraient verts pour la mauvaise
    raison.** Un filtre qui ne rend JAMAIS rien satisfait n'importe quelle
    assertion d'absence. C'est exactement le piège dans lequel un test de
    délégation d'approbation était tombé la semaine dernière : il passait
    avant ET après la correction, sans rien dire du délai d'escalade."""
    d = deux_societes
    with use_tenant(d["b"].id):
        assert FlwExchange.objects.filter(id=d["echange_b"].id).exists()
        assert FlwLink.objects.filter(id=d["liaison_b"].id).exists()
        assert FlwCredential.objects.filter(id=d["secret_b"].id).exists()
        assert FlwPayload.objects.filter(id=d["charge_b"].id).exists()


# --- Les quatre objets, côté manager Django ------------------------------------


@pytest.mark.parametrize(
    "modele,clef",
    [
        (FlwExchange, "echange_b"),
        (FlwLink, "liaison_b"),
        (FlwCredential, "secret_b"),
        (FlwPayload, "charge_b"),
    ],
)
def test_none_of_the_four_objects_is_reachable_by_direct_id(deux_societes, modele, clef) -> None:
    """« Y compris par identifiant direct » : on ne liste pas, on demande
    l'objet PAR SON IDENTIFIANT, celui-là même qu'un écran, un journal ou
    une URL peut avoir laissé fuir."""
    d = deux_societes
    identifiant = d[clef].id
    with use_tenant(d["a"].id):
        assert not modele.objects.filter(id=identifiant).exists()
        with pytest.raises(modele.DoesNotExist):
            modele.objects.get(id=identifiant)


# --- Les quatre objets, côté PostgreSQL ----------------------------------------


@pytest.mark.parametrize(
    "modele,clef",
    [
        (FlwExchange, "echange_b"),
        (FlwLink, "liaison_b"),
        (FlwCredential, "secret_b"),
        (FlwPayload, "charge_b"),
    ],
)
def test_postgresql_itself_refuses_the_other_company_s_rows(deux_societes, modele, clef) -> None:
    """`all_objects` NE FILTRE RIEN côté Django : c'est le manager nu. Si
    ces requêtes rendent l'ensemble vide, c'est la policy PostgreSQL qui
    l'a décidé, et personne d'autre. C'est ce qui distingue une isolation
    tenue par le code d'une isolation tenue par la base — la première
    disparaît au premier service qui oublie un filtre.

    **Falsification faite, et son piège noté.** Désactiver la policy dans
    `psql` avant de lancer pytest ne rougit RIEN : `--reuse-db` rejoue
    `migrate`, et `post_migrate` réapplique `apply_rls`. La falsification
    qui mord fait son `ALTER TABLE flw_exchange DISABLE ROW LEVEL SECURITY`
    DANS la transaction du test, et AVANT toute écriture — PostgreSQL
    refuse un `ALTER TABLE` tant que des déclencheurs de contrainte
    différés sont en attente. Faite ainsi, la ligne de B devient visible
    depuis A, et ces assertions rougissent.
    """
    d = deux_societes
    with use_tenant(d["a"].id):
        assert list(modele.all_objects.filter(id=d[clef].id)) == []


def test_writing_into_the_other_company_is_refused_by_postgresql(deux_societes) -> None:
    """L'autre sens, qui ne se déduit pas du premier : une policy peut être
    posée en lecture et pas en écriture. Écrire une liaison chez B depuis A
    doit être refusé par la base, pas seulement invisible ensuite."""
    d = deux_societes
    with use_tenant(d["a"].id), pytest.raises(ProgrammingError):
        FlwLink.objects.create(tenant=d["b"], connector=d["connecteur_b"], name="liaison intruse")


def test_the_policy_is_really_installed_on_the_five_tables() -> None:
    """La garde statique `test_rls_coverage.py` regarde de quoi les modèles
    HÉRITENT ; elle ne dit rien de ce que PostgreSQL porte réellement. Ce
    test interroge le catalogue.

    **`FORCE` et pas seulement `ENABLE`**, et la nuance est tout le sujet :
    le rôle applicatif `widehalo_app` est PROPRIÉTAIRE des tables, et un
    propriétaire contourne une policy simplement activée. Une table en
    `ENABLE` seul est protégée contre tout le monde sauf le seul rôle qui
    se connecte."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE relname = ANY(%s)",
            [list(TABLES_DU_HUB)],
        )
        etat = {nom: (active, forcee) for nom, active, forcee in cursor.fetchall()}
        cursor.execute(
            "SELECT tablename FROM pg_policies "
            "WHERE policyname = 'tenant_isolation_policy' AND tablename = ANY(%s)",
            [list(TABLES_DU_HUB)],
        )
        avec_policy = {ligne[0] for ligne in cursor.fetchall()}

    for table in TABLES_DU_HUB:
        assert etat.get(table) == (True, True), (
            f"{table} : la RLS doit être ENABLE **et** FORCE — le rôle "
            "applicatif est propriétaire et contournerait un simple ENABLE."
        )
        assert table in avec_policy, f"{table} n'a pas de `tenant_isolation_policy`."


# --- « Par identifiant direct », à travers les services ------------------------


def test_the_replay_services_never_reach_the_other_company_s_exchange(deux_societes) -> None:
    """Les trois services de rejeu prennent une LISTE D'IDENTIFIANTS venue
    d'un écran. C'est la forme exacte que nomme le critère, et le seul
    chemin où un identifiant recopié devient une fuite."""
    d = deux_societes
    ids = [d["echange_b"].id]
    with use_tenant(d["a"].id):
        assert replayable_exchanges(d["a"], ids=ids) == []
        assert estimate_replay(d["a"], ids=ids).count == 0
        assert replay_selection(d["a"], ids=ids) == []


def test_passing_the_other_company_as_an_argument_changes_nothing(deux_societes) -> None:
    """Le contournement le plus direct, et celui qu'un service filtrant
    « par argument » laisserait passer : appeler depuis A en passant
    l'objet `Tenant` de B. Le manager lit le CONTEXTE, jamais l'argument, et
    la policy PostgreSQL non plus."""
    d = deux_societes
    with use_tenant(d["a"].id):
        assert replayable_exchanges(d["b"], ids=[d["echange_b"].id]) == []
        assert (
            flows_public.list_exchanges_for_document(
                d["b"], document_type=_DOCUMENT, document_id=d["document_id"]
            )
            == []
        )
        assert flows_public.count_exchanges_awaiting_verdict(d["b"]) == 0
        assert (
            flows_public.has_active_link(d["b"], connector_code=reference.CONNECTOR_CODE) is False
        )


def test_the_business_history_of_a_document_stays_in_its_own_company(deux_societes) -> None:
    """`list_exchanges_for_document` est le point d'entrée que les modules
    métier appellent depuis une fiche de pièce. Un identifiant de pièce est
    la donnée la plus facilement recopiée du produit."""
    d = deux_societes
    with use_tenant(d["b"].id):
        assert (
            flows_public.list_exchanges_for_document(
                d["b"], document_type=_DOCUMENT, document_id=d["document_id"]
            )
            != []
        ), "Témoin : chez B, l'historique existe."
    with use_tenant(d["a"].id):
        assert (
            flows_public.list_exchanges_for_document(
                d["a"], document_type=_DOCUMENT, document_id=d["document_id"]
            )
            == []
        )


# --- La vidange, la boucle où une erreur d'isolation ne se voit pas ------------


def test_one_company_s_drain_never_calls_for_another_s_exchange(deux_societes) -> None:
    """**Le trou trouvé en reconnaissance.** `run_flows_queue` boucle sur
    `Tenant.objects.all()` — c'est exactement la boucle où une erreur
    d'isolation reste invisible, puisque tout finit de toute façon par être
    traité. Le test qui mord est donc celui d'une passe faite POUR A : elle
    ne doit appeler l'adaptateur pour aucun échange de B."""
    d = deux_societes
    appels = []

    def _mouchard(echange, budget):
        appels.append(echange.id)
        raise AssertionError("un échange d'une autre société a été appelé")

    with use_tenant(d["a"].id):
        comptes = drain_outbound_queue(d["a"], sender=_mouchard)

    assert appels == []
    assert comptes["sent"] == 0
    # La relecture se fait SOUS LE CONTEXTE DE B : `refresh_from_db` passe
    # par `_base_manager`, qui ne filtre rien côté Django — c'est la policy
    # PostgreSQL qui décide, et elle décide en fonction de la société
    # active. Relire hors contexte ne dirait rien de l'isolation, et
    # échouerait pour une raison qui n'est pas celle qu'on teste.
    with use_tenant(d["b"].id):
        d["echange_b"].refresh_from_db()
    assert d["echange_b"].state == FlwExchange.STATE_QUEUED


def test_the_same_exchange_does_leave_on_its_own_company_s_pass(deux_societes) -> None:
    """Le témoin du test précédent. Sans lui, une vidange qui n'appellerait
    jamais personne le laisserait vert."""
    d = deux_societes
    with use_tenant(d["b"].id):
        comptes = process_outbound_queue(d["b"])
        d["echange_b"].refresh_from_db()
    assert comptes["sent"] == 1
    assert d["echange_b"].state == FlwExchange.STATE_ACCEPTED


# --- Le secret, qui mérite une vérification de plus ---------------------------


def test_the_other_company_s_secret_is_never_readable_in_clear(deux_societes) -> None:
    """Le secret est le seul des quatre objets dont la fuite ne se répare
    pas : une facture vue est une indiscrétion, une clef d'API vue est un
    accès. Deux vérifications, donc — l'isolation, et le fait que la
    colonne elle-même ne porte pas le clair."""
    d = deux_societes
    with use_tenant(d["a"].id):
        assert list(FlwCredential.all_objects.filter(id=d["secret_b"].id)) == []

    with connection.cursor() as cursor:
        cursor.execute("SELECT secret FROM flw_credential")
        colonnes = [ligne[0] for ligne in cursor.fetchall()]
    for valeur in colonnes:
        assert "cle-tres-secrete-de-B" not in (valeur or ""), (
            "Le secret est en clair dans la colonne : le chiffrement au repos n'a pas eu lieu."
        )


# --- Hors de toute société ------------------------------------------------------


@pytest.mark.parametrize("modele", [FlwExchange, FlwLink, FlwCredential, FlwPayload, FlwPayload])
def test_outside_any_company_nothing_is_returned(deux_societes, modele) -> None:
    """Deny-by-default. Un code qui a oublié d'activer une société ne doit
    pas voir TOUTES les sociétés — c'est le mode d'échec qui transforme un
    oubli en fuite générale."""
    assert list(modele.objects.all()) == []
