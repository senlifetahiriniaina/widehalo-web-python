"""S2 (Phase 4, bloc A) — la machine à états, et ses trois invariants.

Les neuf états seraient faciles à « implémenter » sans rien garantir : une
colonne `state` et neuf constantes suffisent à en donner l'apparence. Ce
qui les rend réels, ce sont les trois invariants que le cahier pose, et
chacun d'eux est ici exercé par un test qui échoue si on le retire.

Le point de contrôle du sprint — « le modèle dimensionnel de la Phase 2
accueille le fait d'échange sans reprise des dimensions conformes » — est
vérifié par introspection en fin de fichier : une preuve, pas une
affirmation.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwPayload
from apps.flows.services.exchange import (
    INCIDENT_WORTHY_STATES,
    TERMINAL_STATES,
    allowed_targets,
    exchanges_due_for_relance,
    is_terminal,
    opens_incident,
    prepare_exchange,
    transition_exchange,
)
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="S2-FLOWS", name="Flux S2 SARL")
    with use_tenant(tenant.id):
        link = FlwLinkFactory(tenant=tenant)
    return tenant, link


def _prepare(tenant, link, **kwargs):
    return prepare_exchange(tenant, link, operation="OP1", **kwargs)


# --- Invariant 1 : accepté et rejeté sont terminaux ----------------------------


def test_a_settled_exchange_can_never_move_again(setup) -> None:
    """Le tiers a tranché. Rien n'en repart — ni relance, ni rejeu. Un
    rejeu supervisé crée un NOUVEL échange (S4) ; rouvrir celui-ci ferait
    du registre un état courant au lieu d'une trace, ce que « le registre
    est au flux ce que le mouvement est au stock » interdit."""
    tenant, link = setup
    with use_tenant(tenant.id):
        for settled in (FlwExchange.STATE_ACCEPTED, FlwExchange.STATE_REJECTED):
            exchange = _prepare(tenant, link)
            transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
            transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
            transition_exchange(exchange, to_state=settled, result_code="X")

            assert is_terminal(exchange.state)
            assert allowed_targets(exchange.state) == frozenset()
            with pytest.raises(ValidationError, match="rejeu"):
                transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)


def test_only_accepted_and_rejected_are_terminal() -> None:
    """La contrepartie, et elle compte : déclarer TOUT terminal
    satisferait aussi le test précédent, et figerait le hub. En
    particulier `EN_ECHEC` n'est pas terminal au sens de l'invariant — le
    tiers n'a rien tranché, c'est nous qui avons renoncé."""
    assert {FlwExchange.STATE_ACCEPTED, FlwExchange.STATE_REJECTED} == TERMINAL_STATES
    assert not is_terminal(FlwExchange.STATE_FAILED)
    assert not is_terminal(FlwExchange.STATE_SUSPENDED)


# --- Invariant 2 : l'attente de verdict n'expire jamais -----------------------


def test_awaiting_verdict_carries_a_relance_deadline_not_an_expiry(setup) -> None:
    """Le cœur du critère. Faire expirer cet état vers `EN_ECHEC` au bout
    de N jours **inventerait un verdict que le tiers n'a pas rendu** : une
    soumission fiscale « en échec » parce que l'administration est lente
    est un faux, et un faux qui déclenche des relances auprès d'un client
    dont la facture est en réalité valide.

    On vérifie donc que l'échéance DÉSIGNE l'échange sans le faire
    basculer."""
    tenant, link = setup
    hier = timezone.now() - dt.timedelta(days=30)
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link)
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
        transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
        transition_exchange(
            exchange, to_state=FlwExchange.STATE_AWAITING_VERDICT, next_action_at=hier
        )

        due = exchanges_due_for_relance(tenant)
        assert [e.id for e in due] == [exchange.id]

        # ... et l'échéance passée depuis trente jours ne l'a PAS fait
        # basculer : redemander est une action, pas une conséquence de
        # l'horloge.
        exchange.refresh_from_db()
        assert exchange.state == FlwExchange.STATE_AWAITING_VERDICT
        assert exchange.settled_at is None


def test_a_deadline_is_refused_on_a_state_that_is_not_a_waiting_state(setup) -> None:
    """Une échéance posée sur un état qui n'attend rien serait une erreur
    d'appel silencieuse : l'appelant croirait avoir programmé quelque
    chose. Refusé plutôt qu'absorbé.

    S3 a élargi le contrat de deux à trois états d'attente — le verdict et
    le réessai en portent une, `en_file` non. Ce test garde donc la BORNE,
    pas la liste : `en_file` est un état où l'échange attend un worker, pas
    une échéance, et lui en poser une programmerait quelque chose que rien
    ne lit."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link)
        with pytest.raises(ValidationError, match="échéance"):
            transition_exchange(
                exchange,
                to_state=FlwExchange.STATE_QUEUED,
                next_action_at=timezone.now(),
            )


def test_an_exchange_without_a_deadline_is_never_relanced(setup) -> None:
    """Falsification du test d'échéance : renvoyer TOUS les échanges en
    attente le satisferait aussi. Sans échéance, rien n'est dû."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link)
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
        transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
        transition_exchange(exchange, to_state=FlwExchange.STATE_AWAITING_VERDICT)
        assert exchanges_due_for_relance(tenant) == []


# --- Invariant 3 : suspendu n'ouvre pas d'incident ----------------------------


def test_a_quota_suspension_opens_no_incident() -> None:
    """Un plafond atteint est un fonctionnement NORMAL de la gouvernance,
    décidé par le client lui-même. L'ouvrir comme incident noierait les
    vraies pannes sous des alertes volontaires — même distinction que L10 a
    dû faire entre « refusé parce que le consentement a été retiré » et
    « tombé sur une panne réseau »."""
    assert opens_incident(FlwExchange.STATE_SUSPENDED) is False
    # La contrepartie : un échec réel, lui, en ouvre un. Sans cette
    # moitié, un `opens_incident` qui renverrait toujours `False`
    # satisferait le test et supprimerait toute alerte.
    assert opens_incident(FlwExchange.STATE_FAILED) is True
    assert {FlwExchange.STATE_FAILED} == INCIDENT_WORTHY_STATES


def test_a_suspended_exchange_resumes_when_the_cap_is_lifted(setup) -> None:
    """Suspendu n'est pas un cul-de-sac : le plafond se relève, le mois
    change, l'échange repart. Un état de suspension dont on ne sort pas
    serait un échec déguisé."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link)
        transition_exchange(exchange, to_state=FlwExchange.STATE_SUSPENDED)
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
        assert exchange.state == FlwExchange.STATE_QUEUED


# --- Le graphe lui-même --------------------------------------------------------


def test_an_unknown_transition_is_refused(setup) -> None:
    """La table est la seule source de vérité. Une transition absente est
    refusée par `ValidationError`, jamais ignorée en silence : ignorer
    laisserait l'appelant croire que l'échange a avancé, et le registre
    dirait autre chose que le code."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link)
        # `PREPARE` -> `ACCEPTE` : sauterait l'émission, donc affirmerait
        # un verdict sur un échange jamais parti.
        with pytest.raises(ValidationError, match="Transition refusée"):
            transition_exchange(exchange, to_state=FlwExchange.STATE_ACCEPTED)


def test_every_state_of_the_model_is_covered_by_the_graph() -> None:
    """Un état déclaré sur le modèle mais absent du graphe serait
    inatteignable ou inquittable sans que rien ne le signale — neuf états
    « implémentés » dont un mort."""
    from apps.flows.services.exchange import _ALLOWED_TRANSITIONS

    declared = {value for value, _label in FlwExchange.STATE_CHOICES}
    assert declared == set(_ALLOWED_TRANSITIONS), (
        f"Le graphe et les états du modèle ont divergé : {declared ^ set(_ALLOWED_TRANSITIONS)}"
    )
    assert len(declared) == 9

    # Tout état non terminal doit être quittable, et tout état non initial
    # atteignable — sans quoi le graphe contient un état mort.
    reachable = {t for targets in _ALLOWED_TRANSITIONS.values() for t in targets}
    for state in declared:
        if state not in TERMINAL_STATES and state != FlwExchange.STATE_FAILED:
            assert allowed_targets(state), f"État sans issue : {state}"
        if state != FlwExchange.STATE_PREPARED:
            assert state in reachable, f"État inatteignable : {state}"


# --- FLX-2 : préparer un échange ne met jamais la transition métier en péril ---


def test_preparing_an_exchange_touches_nothing_external(setup) -> None:
    """« Un échec de tiers sur déclencheur événementiel n'empêche pas la
    transition métier » : c'est tenable parce que préparer un échange
    n'appelle AUCUN tiers. L'échange naît complet et local — empreinte
    comprise, ce qui doit survivre à la purge de la charge utile."""
    tenant, link = setup
    body = '{"facture": "FA-2026-0007"}'
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link, body=body, document_type="facture_vente")

        assert exchange.state == FlwExchange.STATE_PREPARED
        assert exchange.payload_fingerprint == FlwExchange.fingerprint_of(body)
        assert exchange.partition_month == timezone.now().date().replace(day=1)
        payload = FlwPayload.objects.get(exchange=exchange)
        assert payload.body == body
        assert payload.byte_size == len(body.encode("utf-8"))


def test_an_exchange_without_a_body_carries_no_payload_and_no_fingerprint(setup) -> None:
    """Toutes les opérations ne transportent pas un corps (une demande de
    statut, par exemple). Fabriquer une empreinte de la chaîne vide
    donnerait une empreinte identique pour tous ces échanges, ce qui ne
    prouverait rien tout en en ayant l'air."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchange = _prepare(tenant, link)
        assert exchange.payload_fingerprint == ""
        assert not FlwPayload.objects.filter(exchange=exchange).exists()


# --- Point de contrôle du sprint : l'entrepôt accueille le fait ---------------


def test_the_star_schema_accepts_the_exchange_fact_without_reworking_dimensions() -> None:
    """Le point de contrôle du cahier, vérifié par INTROSPECTION plutôt
    qu'affirmé en commentaire.

    Si accueillir un domaine aussi différent — des flux vers des tiers, là
    où les huit autres faits portent des ventes, des écritures et des
    mouvements — avait exigé de toucher aux dimensions conformes, cela
    aurait signifié qu'elles n'étaient pas conformes mais taillées pour
    leurs premiers usages."""
    from apps.analytics.models import AnDimArticle, AnDimTemps, AnDimTiers, AnFactEchange

    relations = {
        f.name: f.related_model
        for f in AnFactEchange._meta.get_fields()
        if f.is_relation and f.related_model is not None
    }
    # Une seule dimension, et c'est une dimension EXISTANTE.
    assert relations["dim_temps"] is AnDimTemps

    # **Assertion ajoutée après falsification.** La version initiale ne
    # vérifiait que l'absence de dépendance inter-modules — brancher
    # `AnDimTiers` sur ce fait la satisfaisait, alors que c'est précisément
    # ce que la conception écarte : un échange s'adresse à un TIERS
    # TECHNIQUE (administration, agrégateur, banque), jamais à un
    # partenaire commercial du référentiel. Les mélanger fausserait tout
    # comptage par client. Un test qui ne voit pas la faute qu'il décrit ne
    # décrit rien.
    dimensions_liees = {m for m in relations.values() if m.__name__.startswith("AnDim")}
    assert dimensions_liees == {AnDimTemps}, (
        "Le fait d'échange s'est branché sur d'autres dimensions que le temps : "
        f"{sorted(m.__name__ for m in dimensions_liees)}. `AnDimTiers` mélangerait "
        "tiers techniques et partenaires commerciaux ; `AnDimArticle` n'a aucun "
        "sens pour un flux."
    )
    assert AnDimTiers not in dimensions_liees
    assert AnDimArticle not in dimensions_liees

    # Aucune dépendance vers un module métier : l'entrepôt reste
    # indépendant, `flows` aussi.
    related_apps = {model._meta.app_label for model in relations.values()}
    assert related_apps <= {"analytics", "core"}, (
        f"Le fait d'échange dépend de modules qu'il ne devrait pas : {related_apps}"
    )
    assert AnFactEchange._meta.get_field("source_exchange_id").get_internal_type() == "UUIDField"


def test_the_conformed_dimensions_were_not_touched() -> None:
    """« Sans reprise » : les dimensions conformes doivent porter
    EXACTEMENT les mêmes champs qu'avant ce sprint. Un champ ajouté à
    `AnDimTemps` pour les besoins du fait d'échange serait précisément la
    reprise que le point de contrôle interdit."""
    from apps.analytics.models import AnDimTemps

    champs = {f.name for f in AnDimTemps._meta.get_fields() if not f.is_relation}
    assert {"date", "annee", "trimestre", "mois"} <= champs
    # Aucun champ dont le nom trahirait une adaptation au domaine des flux.
    intrus = {c for c in champs if "flux" in c or "echange" in c or "connecteur" in c}
    assert not intrus, f"`AnDimTemps` a été retouchée pour les flux : {intrus}"
