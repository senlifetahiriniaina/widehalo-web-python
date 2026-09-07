"""S4 — FLX-4, et la distinction que le mot « rejeu » recouvre.

Le critère : « Un rejeu d'un échange sortant transmet la même clé
d'idempotence et ne crée aucun doublon chez un tiers d'essai qui la
respecte. »

Le cahier §13.4 le contredit à demi-mot — « une clé calculée sur la pièce,
la liaison et **le rang de tentative** » — et la contradiction n'est pas
anodine : une clé qui change à chaque tentative annule exactement ce que la
phrase suivante promet. Le critère fait foi, et « rang de tentative » ne
peut donc désigner que le rang du REJEU SUPERVISÉ, jamais le compteur
`attempt` du réessai technique.

D'où deux comportements opposés, tous deux testés ici :

- **réessai technique** — même échange, même clé. Le tiers déduplique.
- **rejeu supervisé** — nouvel échange, clé NEUVE, même corrélation. Le
  tiers traite, parce que c'est ce que l'exploitant vient de demander.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.idempotency import (
    assign_keys,
    compute_correlation_key,
    compute_idempotency_key,
    lineage,
)
from apps.flows.services.queue import queue_exchange
from apps.flows.services.replay import (
    estimate_replay,
    replay_exchange,
    replay_selection,
)
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="S4", name="Idempotence SARL")
    with use_tenant(tenant.id):
        link = FlwLinkFactory(tenant=tenant, max_attempts=2, breaker_threshold=99)
    return tenant, link


def _prepared(tenant, link, document_id=None):
    return prepare_exchange(
        tenant,
        link,
        operation="soumettre_facture",
        document_type="facture_vente",
        document_id=document_id or uuid.uuid4(),
        body='{"montant": 1500000}',
    )


# --- FLX-4 : la clé ne bouge pas d'une tentative à l'autre --------------------


def test_the_key_does_not_change_between_technical_retries(setup) -> None:
    """Le cœur du critère. Une clé recalculée à chaque tentative ferait
    traiter chaque réessai comme un envoi neuf par le tiers — soit
    exactement le doublon que l'idempotence existe pour empêcher."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepared(tenant, link)
        queue_exchange(exchange)
        premiere = exchange.idempotency_key
        assert premiere != ""

        # Une tentative échoue, l'échange revient en file, on repasse par le
        # même chemin : la clé ne doit pas bouger.
        transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
        transition_exchange(exchange, to_state=FlwExchange.STATE_TO_RETRY, next_action_at=None)
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
        assign_keys(exchange)

    exchange.refresh_from_db()
    assert exchange.idempotency_key == premiere, (
        "La clé d'idempotence a changé entre deux tentatives du même envoi : le tiers "
        "traitera le réessai comme un envoi neuf, et FLX-4 n'est pas tenu."
    )
    assert exchange.attempt >= 1, "Le compteur de tentatives, lui, doit avoir bougé."


def test_the_attempt_counter_does_not_enter_the_key(setup) -> None:
    """Falsification directe de l'énoncé littéral de §13.4 : si le rang de
    tentative entrait dans la clé, celle-ci changerait à chaque essai."""
    identifiant = uuid.uuid4()
    a = compute_idempotency_key(
        link_id=identifiant, document_type="f", document_id=identifiant, operation="op"
    )
    b = compute_idempotency_key(
        link_id=identifiant, document_type="f", document_id=identifiant, operation="op"
    )
    assert a == b


def test_the_operation_enters_the_key(setup) -> None:
    """Une même pièce peut partir deux fois vers la même liaison pour deux
    opérations différentes — soumettre une facture, puis en demander le
    statut. Sans l'opération dans la clé, la seconde porterait celle de la
    première et le tiers l'ignorerait comme un doublon."""
    identifiant = uuid.uuid4()
    soumission = compute_idempotency_key(
        link_id=identifiant, document_type="f", document_id=identifiant, operation="soumettre"
    )
    statut = compute_idempotency_key(
        link_id=identifiant, document_type="f", document_id=identifiant, operation="statut"
    )
    assert soumission != statut


def test_two_documents_never_share_a_key(setup) -> None:
    liaison = uuid.uuid4()
    a = compute_idempotency_key(
        link_id=liaison, document_type="f", document_id=uuid.uuid4(), operation="op"
    )
    b = compute_idempotency_key(
        link_id=liaison, document_type="f", document_id=uuid.uuid4(), operation="op"
    )
    assert a != b


def test_the_key_is_assigned_at_queueing_not_at_preparation(setup) -> None:
    """Un échange préparé puis abandonné ne doit pas consommer de clé : la
    contrainte d'unicité la retiendrait pour toujours, et une seconde
    tentative sur la même pièce serait refusée par la base pour un envoi
    qui n'a jamais eu lieu."""
    tenant, link = setup
    with use_tenant(tenant.id):
        abandonne = _prepared(tenant, link)
        assert abandonne.idempotency_key == ""

        # La même pièce repart plus tard : rien ne l'en empêche.
        seconde = _prepared(tenant, link, document_id=abandonne.document_id)
        queue_exchange(seconde)
        assert seconde.idempotency_key != ""


# --- La corrélation relie une lignée -----------------------------------------


def test_the_correlation_key_is_computable_from_the_document_alone(setup) -> None:
    """C'est ce qui permet à une notification entrante — qui ne connaît ni
    la liaison ni l'opération, et arrive parfois trois jours plus tard — de
    retrouver l'échange qui l'a déclenchée."""
    identifiant = uuid.uuid4()
    assert (
        compute_correlation_key(document_type="facture_vente", document_id=identifiant)
        == f"facture_vente:{identifiant}"
    )


def test_an_operation_without_a_document_correlates_nothing(setup) -> None:
    """Corréler ce qui ne se rattache à rien produirait des grappes
    d'échanges sans lien entre eux, et le journal deviendrait illisible là
    où il doit être le plus clair."""
    assert compute_correlation_key(document_type="", document_id=None) == ""


def test_a_lineage_gathers_the_successor_with_its_predecessor(setup) -> None:
    """La question à laquelle la corrélation doit répondre : « qu'est
    devenue cette facture ? »."""
    tenant, link = setup
    with use_tenant(tenant.id):
        origine = _prepared(tenant, link)
        queue_exchange(origine)
        transition_exchange(origine, to_state=FlwExchange.STATE_SENT)
        transition_exchange(origine, to_state=FlwExchange.STATE_FAILED)

        successeur = replay_exchange(origine)
        ligne = lineage(tenant.id, origine.correlation_key)

    assert [e.id for e in ligne] == [origine.id, successeur.id]


def test_the_lineage_survives_one_broken_path_but_not_two(setup) -> None:
    """La lignée est portée par DEUX chemins indépendants, et il vaut mieux
    le savoir que le découvrir.

    `replay_exchange` transmet la clé de corrélation explicitement, et
    `assign_keys` sait par ailleurs la recalculer depuis la pièce. La
    falsification l'a montré : casser l'un des deux ne fait pas rougir le
    test précédent — il a fallu les muter tous les deux. Ce test nomme la
    redondance plutôt que de la laisser passer pour un test faible.

    Il vérifie donc le second chemin SEUL : un successeur créé sans
    corrélation explicite la retrouve depuis sa pièce."""
    tenant, link = setup
    with use_tenant(tenant.id):
        origine = _prepared(tenant, link)
        queue_exchange(origine)

        orphelin = prepare_exchange(
            tenant,
            link,
            operation=origine.operation,
            document_type=origine.document_type,
            document_id=origine.document_id,
        )
        assert orphelin.correlation_key == ""
        # Rang de successeur : sans lui, la clé d'idempotence serait celle
        # de l'origine et la contrainte d'unicité la refuserait — ce
        # qu'elle a fait au premier jet de ce test, correctement.
        assign_keys(orphelin, replay_rank=1)

    assert orphelin.correlation_key == origine.correlation_key, (
        "Le second chemin ne recalcule pas la corrélation depuis la pièce : une "
        "lignée créée hors du rejeu supervisé ne se rattacherait à rien."
    )


# --- Le rejeu supervisé crée, il ne réécrit pas -------------------------------


def test_a_replay_creates_a_successor_with_a_new_key(setup) -> None:
    """« Un rejeu crée de nouveaux échanges, il ne réécrit jamais les
    anciens : l'historique des tentatives est la pièce qui explique une
    facture de tiers. »

    Et la clé du successeur doit DIFFÉRER : lui donner celle de son
    prédécesseur ferait ignorer la resoumission par le tiers — l'inverse
    exact de ce que l'exploitant vient de demander."""
    tenant, link = setup
    with use_tenant(tenant.id):
        origine = _prepared(tenant, link)
        queue_exchange(origine)
        cle_origine = origine.idempotency_key
        transition_exchange(origine, to_state=FlwExchange.STATE_SENT)
        transition_exchange(origine, to_state=FlwExchange.STATE_FAILED)

        successeur = replay_exchange(origine)
        origine.refresh_from_db()

    assert successeur.id != origine.id
    assert origine.state == FlwExchange.STATE_FAILED, (
        "L'échange d'origine a été réécrit : l'historique des tentatives est perdu."
    )
    assert successeur.idempotency_key != cle_origine, (
        "Le successeur porte la clé de son prédécesseur : le tiers ignorera la "
        "resoumission comme un doublon."
    )
    assert successeur.correlation_key == origine.correlation_key
    assert successeur.state == FlwExchange.STATE_QUEUED
    assert successeur.payload_fingerprint == origine.payload_fingerprint, (
        "Le successeur rejoue le même contenu : son empreinte doit être celle de "
        "l'original, y compris après purge de la charge utile (FLX-5)."
    )


def test_a_settled_exchange_is_never_replayed(setup) -> None:
    """Invariant 1. Rejouer un échange accepté créerait un doublon chez le
    tiers ; en rejouer un rejeté sans avoir corrigé la pièce reproduirait
    le refus."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepared(tenant, link)
        queue_exchange(exchange)
        transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
        transition_exchange(exchange, to_state=FlwExchange.STATE_ACCEPTED)

        with pytest.raises(ValidationError, match="verdict"):
            replay_exchange(exchange)


def test_two_successive_replays_carry_two_different_keys(setup) -> None:
    """Sans quoi la contrainte d'unicité en base refuserait le second, et
    l'exploitant verrait une `IntegrityError` pour une action légitime."""
    tenant, link = setup
    with use_tenant(tenant.id):
        origine = _prepared(tenant, link)
        queue_exchange(origine)
        transition_exchange(origine, to_state=FlwExchange.STATE_SENT)
        transition_exchange(origine, to_state=FlwExchange.STATE_FAILED)

        premier = replay_exchange(origine)
        transition_exchange(premier, to_state=FlwExchange.STATE_SENT)
        transition_exchange(premier, to_state=FlwExchange.STATE_FAILED)
        second = replay_exchange(premier)

    cles = {origine.idempotency_key, premier.idempotency_key, second.idempotency_key}
    assert len(cles) == 3, f"Clés non distinctes : {cles}"


# --- L'estimation avant confirmation -----------------------------------------


def test_the_estimate_gives_volume_and_cost_before_anything_happens(setup) -> None:
    """« Le panneau de rejeu affiche le volume et le coût estimé avant
    confirmation. Le rejeu de masse sans estimation est la première cause
    de facture surprise. »"""
    from decimal import Decimal

    tenant, link = setup
    with use_tenant(tenant.id):
        identifiants = []
        for _ in range(3):
            exchange = _prepared(tenant, link)
            queue_exchange(exchange)
            transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
            transition_exchange(exchange, to_state=FlwExchange.STATE_FAILED)
            exchange.cost_ariary = Decimal("120")
            exchange.cost_unit = "message"
            exchange.save(update_fields=["cost_ariary", "cost_unit"])
            identifiants.append(exchange.id)

        estimation = estimate_replay(tenant, ids=identifiants)
        # Rien n'a bougé : estimer n'engage pas.
        assert FlwExchange.objects.filter(tenant=tenant).count() == 3

    assert estimation.count == 3
    assert estimation.cost_ariary == Decimal("360")
    assert estimation.is_cost_certain


def test_an_estimate_says_when_it_is_only_a_floor(setup) -> None:
    """Annoncer « 12 000 Ar » pour une sélection dont la moitié n'est pas
    tarifée, c'est annoncer un plancher en le présentant comme un total."""
    from decimal import Decimal

    tenant, link = setup
    with use_tenant(tenant.id):
        identifiants = []
        for index in range(2):
            exchange = _prepared(tenant, link)
            queue_exchange(exchange)
            transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
            transition_exchange(exchange, to_state=FlwExchange.STATE_FAILED)
            if index == 0:
                exchange.cost_ariary = Decimal("120")
                exchange.save(update_fields=["cost_ariary"])
            identifiants.append(exchange.id)

        estimation = estimate_replay(tenant, ids=identifiants)

    assert estimation.count == 2
    assert estimation.cost_ariary == Decimal("120")
    assert estimation.unpriced_count == 1
    assert not estimation.is_cost_certain


def test_a_selection_ignores_what_can_no_longer_be_replayed(setup) -> None:
    """Une sélection faite à l'écran peut contenir une ligne qu'un autre
    utilisateur vient de rejouer. Faire échouer l'opération entière pour
    cela obligerait à tout recommencer."""
    tenant, link = setup
    with use_tenant(tenant.id):
        rejouable = _prepared(tenant, link)
        queue_exchange(rejouable)
        transition_exchange(rejouable, to_state=FlwExchange.STATE_SENT)
        transition_exchange(rejouable, to_state=FlwExchange.STATE_FAILED)

        tranche = _prepared(tenant, link)
        queue_exchange(tranche)
        transition_exchange(tranche, to_state=FlwExchange.STATE_SENT)
        transition_exchange(tranche, to_state=FlwExchange.STATE_ACCEPTED)

        successeurs = replay_selection(tenant, ids=[rejouable.id, tranche.id])

    assert len(successeurs) == 1
    assert successeurs[0].correlation_key == rejouable.correlation_key
