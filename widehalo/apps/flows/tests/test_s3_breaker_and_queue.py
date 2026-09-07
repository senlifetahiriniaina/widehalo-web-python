"""S3 — FLX-3, clause par clause, et ce que chaque clause interdit.

Le critère tient en une phrase et en contient quatre : « Après N échecs
consécutifs sur une liaison, [1] le disjoncteur s'ouvre, [2] les échanges
suivants restent en file [3] sans appel réseau, et [4] un incident unique
est créé — pas un incident par tentative. »

Les quatre sont testées séparément, parce qu'une implémentation peut en
tenir trois. En particulier [2] et [3] sont deux choses différentes : un
disjoncteur qui basculerait les échanges en échec tiendrait [3] et
violerait [2], et l'utilisateur verrait une file vide alors que rien n'est
parti.

Le mot **CONSÉCUTIFS** a son test à lui : c'est le seul mot du critère
qu'une implémentation cumulative satisferait en apparence pendant des mois
avant d'ouvrir le disjoncteur d'une liaison qui marche.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwIncident, FlwLink
from apps.flows.operations import (
    OP_DROP_FILE,
    OP_INITIATE_PAYMENT,
    OP_PUBLISH_DATASET,
    OP_PUSH_DOCUMENT,
    OP_QUERY_REFERENCE,
    OP_SUBMIT_FOR_VERDICT,
)
from apps.flows.services.exchange import prepare_exchange
from apps.flows.services.incidents import RECOVERY_ACTIONS, record_failure, resolve_incident
from apps.flows.services.queue import (
    CallOutcome,
    breaker_allows,
    drain_outbound_queue,
    due_exchanges,
    next_attempt_delay_seconds,
    open_breakers,
    outbound_queue_depth,
    record_call_failure,
    record_call_success,
)
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db

#: Les six opérations SORTANTES, dans l'ordre du cahier. OP6 et OP7 sont
#: entrantes et n'ont donc rien à faire dans une file de sortie.
_OPERATIONS_SORTANTES = [
    OP_PUSH_DOCUMENT,
    OP_PUBLISH_DATASET,
    OP_DROP_FILE,
    OP_SUBMIT_FOR_VERDICT,
    OP_INITIATE_PAYMENT,
    OP_QUERY_REFERENCE,
]


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="S3-FLUX", name="Flux S3 SARL")
    with use_tenant(tenant.id):
        connector = FlwConnectorFactory(tenant=tenant, code="dgi")
        link = FlwLinkFactory(
            tenant=tenant,
            connector=connector,
            state=FlwLink.STATE_ACTIVE,
            breaker_threshold=3,
            max_attempts=10,
            retry_backoff_seconds=60,
            breaker_cooldown_seconds=900,
        )
    return tenant, link


def _queue(tenant, link, count=1):
    """`count` échanges prêts à partir, en `en_file`.

    L'opération tourne sur les six opérations SORTANTES du jeu fermé (S6) :
    `f"OP{index}"` produisait « OP0 », qui n'a jamais existé, et le jeu
    fermé le refuse désormais à la préparation. Les entrantes (OP6, OP7)
    sont exclues — une passe de vidange est sortante par construction."""
    from apps.flows.services.exchange import transition_exchange

    out = []
    for index in range(count):
        exchange = prepare_exchange(
            tenant,
            link,
            operation=_OPERATIONS_SORTANTES[index % 6],
            # Un corps, sans quoi l'échange ne peut plus être émis depuis S6
            # (FLX-1). L'index entre dedans : deux échanges d'une même passe
            # doivent porter deux empreintes distinctes, sinon le registre ne
            # prouve rien de ce qui est parti.
            body=f'{{"rang": {index}}}',
        )
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
        out.append(exchange)
    return out


def _always_fails(family=FlwIncident.FAMILY_UNAVAILABLE):
    calls = []

    def sender(exchange, budget):
        calls.append(exchange.id)
        return CallOutcome(ok=False, result_code="503", result_message="indispo", family=family)

    sender.calls = calls
    return sender


def _always_succeeds():
    calls = []

    def sender(exchange, budget):
        calls.append(exchange.id)
        return CallOutcome(ok=True, result_code="200")

    sender.calls = calls
    return sender


# --- Clause 1 : le disjoncteur s'ouvre au Nième échec --------------------------


def test_the_breaker_opens_after_n_consecutive_failures_and_not_before(setup) -> None:
    """N, pas N-1 et pas 1. Un disjoncteur qui s'ouvrirait au premier échec
    couperait une liaison saine sur un incident de réseau isolé — et le
    seuil réglable de l'axe A5 ne servirait alors à rien."""
    tenant, link = setup
    with use_tenant(tenant.id):
        for _ in range(link.breaker_threshold - 1):
            record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert link.breaker_state == FlwLink.BREAKER_CLOSED, (
            "Le disjoncteur s'est ouvert AVANT son seuil : le réglage de l'axe A5 "
            "n'est pas celui qui décide."
        )

        record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert link.breaker_state == FlwLink.BREAKER_OPEN
        assert link.breaker_opened_at is not None


def test_a_success_resets_the_consecutive_counter(setup) -> None:
    """« CONSÉCUTIFS ». Sans cette remise à zéro le compteur est cumulatif,
    et une liaison qui échoue deux fois par mois finit par ouvrir son
    disjoncteur au bout d'un trimestre de fonctionnement normal — une panne
    fabriquée par le mécanisme censé les éviter."""
    tenant, link = setup
    with use_tenant(tenant.id):
        record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert link.consecutive_failures == 2

        record_call_success(link)
        assert link.consecutive_failures == 0

        # Et deux échecs de plus ne suffisent toujours pas : le compteur est
        # bien reparti de zéro, il n'a pas été seulement affiché à zéro.
        record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert link.breaker_state == FlwLink.BREAKER_CLOSED


def test_the_breaker_is_per_link_not_per_connector(setup) -> None:
    """L'arbitrage écrit sur `FlwLink`, vérifié plutôt que commenté.

    Deux liaisons d'un même tenant sur un même connecteur — le point
    d'essai et le point de production. Ouvrir le disjoncteur du connecteur
    parce que l'essai répond mal couperait la production : c'est
    exactement la panne que ce mécanisme existe pour éviter."""
    tenant, link = setup
    with use_tenant(tenant.id):
        autre = FlwLinkFactory(
            tenant=tenant,
            connector=link.connector,
            name="point d'essai",
            state=FlwLink.STATE_ACTIVE,
            breaker_threshold=3,
        )
        for _ in range(3):
            record_call_failure(autre, family=FlwIncident.FAMILY_UNAVAILABLE)

        assert autre.breaker_state == FlwLink.BREAKER_OPEN
        link.refresh_from_db()
        assert link.breaker_state == FlwLink.BREAKER_CLOSED, (
            "Le disjoncteur d'une liaison a coupé une AUTRE liaison du même "
            "connecteur : le grain est celui du connecteur, pas celui du critère."
        )


# --- Clauses 2 et 3 : en file, sans appel réseau -------------------------------


def test_an_open_breaker_leaves_the_exchanges_queued_and_calls_nothing(setup) -> None:
    """Les deux clauses ensemble, et la falsification de chacune.

    « restent en file » : l'état ne bouge pas — ni échec, ni suspendu.
    « sans appel réseau » : l'adaptateur n'est pas appelé du tout. Compter
    les appels est le seul moyen de le vérifier ; assurer que l'état n'a
    pas bougé laisserait passer une implémentation qui appelle le tiers
    puis ignore la réponse."""
    tenant, link = setup
    with use_tenant(tenant.id):
        for _ in range(link.breaker_threshold):
            record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert link.breaker_state == FlwLink.BREAKER_OPEN

        exchanges = _queue(tenant, link, count=3)
        sender = _always_succeeds()
        counts = drain_outbound_queue(tenant, sender=sender)

        assert sender.calls == [], "Le disjoncteur est ouvert et un appel réseau a eu lieu."
        assert counts["skipped_breaker"] == 3
        for exchange in exchanges:
            exchange.refresh_from_db()
            assert exchange.state == FlwExchange.STATE_QUEUED, (
                "L'échange a quitté la file alors que le critère demande qu'il y reste."
            )
            assert exchange.attempt == 0


# --- Clause 4 : un incident unique --------------------------------------------


def test_repeated_failures_produce_one_incident_not_one_per_attempt(setup) -> None:
    """Le cœur du critère. Une plateforme injoignable une nuit produit des
    dizaines de tentatives ; un incident par tentative rendrait la console
    illisible et l'indicateur « incidents non traités sous 48 h »
    inexploitable."""
    tenant, link = setup
    with use_tenant(tenant.id):
        # Des codes DIFFÉRENTS à chaque tentative : sinon l'assertion sur le
        # dernier code serait vraie que l'incident le reprenne ou qu'il ait
        # simplement gardé celui de sa création. C'est exactement ce que la
        # falsification a montré.
        for numero in range(7):
            record_call_failure(
                link, family=FlwIncident.FAMILY_UNAVAILABLE, result_code=f"503-{numero}"
            )

        incidents = FlwIncident.objects.filter(link=link)
        assert incidents.count() == 1, (
            f"{incidents.count()} incidents pour 7 tentatives : le critère demande un "
            "incident unique."
        )
        incident = incidents.get()
        assert incident.occurrence_count == 7, (
            "Une seule ligne, mais un compteur qui ne compte pas : la console ne "
            "distinguerait plus une panne isolée d'une panne qui dure."
        )
        assert incident.last_result_code == "503-6", (
            "L'incident affiche le premier code d'erreur, pas le dernier : le "
            "diagnostic porterait sur une tentative vieille de sept essais."
        )


def test_the_database_refuses_a_second_live_incident_for_one_family(setup) -> None:
    """Ce qui tient RÉELLEMENT FLX-3, et il vaut mieux le savoir.

    La falsification du test précédent est passée : couper la
    déduplication du service ne produit toujours qu'un incident, parce que
    c'est la contrainte partielle en base qui rejette le doublon et que le
    service se contente de rattraper le rejet. La garantie est donc plus
    forte qu'un `if` — un import, une commande ou un second worker ne
    peuvent pas la contourner — mais elle vivait sans test qui la nomme.

    Celui-ci s'adresse à la base directement. Le jour où quelqu'un
    supprimera la contrainte en croyant simplifier, c'est lui qui
    l'arrêtera."""
    tenant, link = setup
    with use_tenant(tenant.id):
        record_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        with pytest.raises(IntegrityError):
            FlwIncident.objects.create(
                tenant=tenant,
                link=link,
                family=FlwIncident.FAMILY_UNAVAILABLE,
                state=FlwIncident.STATE_OPEN,
                first_seen_at=timezone.now(),
                last_seen_at=timezone.now(),
            )


def test_an_acknowledged_incident_still_blocks_a_duplicate(setup) -> None:
    """« Pris en charge » est un état VIVANT. Un incident sur lequel
    quelqu'un travaille ne doit pas se dédoubler à l'échec suivant —
    sinon le support verrait apparaître un second incident pour la panne
    qu'il est en train de traiter."""
    tenant, link = setup
    with use_tenant(tenant.id):
        incident = record_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        incident.state = FlwIncident.STATE_ACKNOWLEDGED
        incident.save(update_fields=["state"])

        encore = record_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert encore.pk == incident.pk
        assert encore.occurrence_count == 2
        assert FlwIncident.objects.filter(link=link).count() == 1


def test_two_different_families_on_one_link_are_two_incidents(setup) -> None:
    """La contrepartie, et elle compte autant. §10.3 associe à chaque
    famille UNE action de reprise : fondre un jeton expiré et une
    plateforme injoignable en un seul incident rendrait l'action proposée
    fausse dans un cas sur deux."""
    tenant, link = setup
    with use_tenant(tenant.id):
        record_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        record_failure(link, family=FlwIncident.FAMILY_CREDENTIALS)

        assert FlwIncident.objects.filter(link=link).count() == 2
        familles = set(FlwIncident.objects.filter(link=link).values_list("family", flat=True))
        assert familles == {FlwIncident.FAMILY_UNAVAILABLE, FlwIncident.FAMILY_CREDENTIALS}


def test_a_resolved_incident_no_longer_blocks_the_next_one(setup) -> None:
    """Une liaison réparée puis retombée en panne doit rouvrir un incident
    NEUF. Sans cela, la deuxième panne serait muette — et sa première
    occurrence remonterait à la première panne, faussant la seule mesure
    qui dit depuis combien de temps ça dure."""
    tenant, link = setup
    with use_tenant(tenant.id):
        premier = record_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        resolve_incident(premier)

        second = record_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert second.pk != premier.pk
        assert second.occurrence_count == 1
        assert FlwIncident.objects.filter(link=link).count() == 2


def test_every_error_family_has_a_recovery_action() -> None:
    """§10.3 : « un jeu fermé de six familles, chacune associée à une action
    de reprise unique ». Une famille sans action produirait, dans la
    console, un incident qui ne dit pas quoi faire."""
    familles = {code for code, _label in FlwIncident.FAMILY_CHOICES}
    assert set(RECOVERY_ACTIONS) == familles, (
        "Familles sans action de reprise : "
        f"{sorted(familles - set(RECOVERY_ACTIONS))} ; actions orphelines : "
        f"{sorted(set(RECOVERY_ACTIONS) - familles)}."
    )


def test_a_failure_without_a_known_family_is_refused(setup) -> None:
    """Une erreur brute remontée telle quelle est précisément ce que §10.3
    interdit. Elle est refusée à l'écriture plutôt que stockée."""
    tenant, link = setup
    with use_tenant(tenant.id), pytest.raises(KeyError, match="six familles"):
        record_failure(link, family="timeout_reseau")

    with pytest.raises(ValueError, match="six familles"):
        CallOutcome(ok=False, family="timeout_reseau")


# --- La période d'essai --------------------------------------------------------


def test_an_open_breaker_reopens_the_line_after_the_trial_period(setup) -> None:
    """Le glossaire du cahier définit le disjoncteur comme se refermant
    « après une période d'essai ». Sans elle, un disjoncteur ouvert une nuit
    coupe la liaison jusqu'à ce qu'un humain la rouvre."""
    tenant, link = setup
    with use_tenant(tenant.id):
        ouverture = timezone.now()
        for _ in range(link.breaker_threshold):
            record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE, now=ouverture)
        assert link.breaker_state == FlwLink.BREAKER_OPEN

        # Pendant la période d'essai : toujours fermé au trafic.
        pendant = ouverture + dt.timedelta(seconds=link.breaker_cooldown_seconds - 1)
        assert breaker_allows(link, now=pendant) is False

        apres = ouverture + dt.timedelta(seconds=link.breaker_cooldown_seconds + 1)
        assert breaker_allows(link, now=apres) is True
        assert link.breaker_state == FlwLink.BREAKER_HALF_OPEN


def test_a_failed_trial_call_reopens_the_breaker_immediately(setup) -> None:
    """L'appel d'essai pose une question ; sa réponse est non. Attendre à
    nouveau le seuil complet ferait passer N-1 appels de plus vers un tiers
    dont on vient de vérifier qu'il est toujours en panne."""
    tenant, link = setup
    with use_tenant(tenant.id):
        link.breaker_state = FlwLink.BREAKER_HALF_OPEN
        link.consecutive_failures = 0
        link.save(update_fields=["breaker_state", "consecutive_failures"])

        record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)
        assert link.breaker_state == FlwLink.BREAKER_OPEN
        assert link.consecutive_failures == 1


def test_a_successful_trial_call_closes_the_breaker(setup) -> None:
    tenant, link = setup
    with use_tenant(tenant.id):
        link.breaker_state = FlwLink.BREAKER_HALF_OPEN
        link.consecutive_failures = 4
        link.save(update_fields=["breaker_state", "consecutive_failures"])

        record_call_success(link)
        assert link.breaker_state == FlwLink.BREAKER_CLOSED
        assert link.breaker_opened_at is None


# --- L'alerte d'ouverture (§7.6 et axe A5) -------------------------------------


def test_opening_the_breaker_notifies_the_configured_recipient(setup) -> None:
    """« Une alerte sur l'ouverture d'un disjoncteur » (§7.6), adressée au
    destinataire réglé sur l'axe A5.

    Ce test existe surtout pour une raison de méthode : `alert_recipient`
    est un champ que le client renseigne, et un champ écrit sans lecteur
    est le défaut que ce projet corrige depuis le début. Sans ce test, le
    lecteur existerait sans que rien ne prouve qu'il lit."""
    from apps.core.models.notification import Notification
    from apps.core.tests.factories import UserFactory

    tenant, link = setup
    with use_tenant(tenant.id):
        destinataire = UserFactory()
        link.alert_recipient = destinataire
        link.save(update_fields=["alert_recipient"])

        for _ in range(link.breaker_threshold):
            record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)

        alertes = Notification.objects.filter(
            tenant_id=tenant.id, notification_type="flows.breaker_opened"
        )
        assert alertes.count() == 1, (
            f"{alertes.count()} alerte(s) pour une ouverture : le destinataire réglé "
            "sur la liaison n'est pas prévenu, ou l'est à chaque échec."
        )
        charge = alertes.get().payload
        assert charge["link"] == link.name
        # L'action de reprise voyage AVEC l'alerte : une alerte qui dit
        # qu'une liaison est coupée sans dire quoi faire oblige à ouvrir la
        # console pour l'apprendre.
        assert "renouveler" in charge["action"].lower() or len(charge["action"]) > 40


def test_a_breaker_already_open_does_not_alert_again(setup) -> None:
    """Un échec de plus sur un disjoncteur déjà ouvert ne réalerte pas.
    L'alerte porte la TRANSITION, pas l'état — sinon une panne nocturne
    enverrait une notification par tentative, ce qui est exactement le
    bruit que « un incident unique » cherche à éviter."""
    from apps.core.models.notification import Notification
    from apps.core.tests.factories import UserFactory

    tenant, link = setup
    with use_tenant(tenant.id):
        link.alert_recipient = UserFactory()
        link.save(update_fields=["alert_recipient"])
        for _ in range(link.breaker_threshold + 4):
            record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)

        assert (
            Notification.objects.filter(
                tenant_id=tenant.id, notification_type="flows.breaker_opened"
            ).count()
            == 1
        )


def test_a_link_without_a_recipient_alerts_nobody_and_still_records(setup) -> None:
    """Sans destinataire configuré, rien n'est émis — et c'est volontaire :
    envoyer à un rôle par défaut ferait recevoir à quelqu'un une alerte
    qu'il n'a pas demandée, sur une liaison qu'il ne connaît pas.
    L'incident, lui, reste la trace dans tous les cas."""
    from apps.core.models.notification import Notification

    tenant, link = setup
    with use_tenant(tenant.id):
        assert link.alert_recipient_id is None
        for _ in range(link.breaker_threshold):
            record_call_failure(link, family=FlwIncident.FAMILY_UNAVAILABLE)

        assert not Notification.objects.filter(
            tenant_id=tenant.id, notification_type="flows.breaker_opened"
        ).exists()
        assert link.breaker_state == FlwLink.BREAKER_OPEN
        assert FlwIncident.objects.filter(link=link).count() == 1


# --- Le réessai espacé ---------------------------------------------------------


def test_the_backoff_grows_and_starts_at_the_configured_value(setup) -> None:
    """« Espacement croissant » (cahier §6). Le premier réessai vaut
    exactement ce que le client a réglé : un exposant qui partirait de 1
    triplerait son réglage à son insu."""
    tenant, link = setup
    assert next_attempt_delay_seconds(link, 1) == 60
    assert next_attempt_delay_seconds(link, 2) == 180
    assert next_attempt_delay_seconds(link, 3) == 540
    # Croissant, strictement.
    delais = [next_attempt_delay_seconds(link, n) for n in range(1, 6)]
    assert delais == sorted(delais) and len(set(delais)) == len(delais)


def test_a_failed_send_schedules_a_retry_and_is_not_due_before_it(setup) -> None:
    """L'espacement doit être OPPOSABLE : un échange réessayé sans attendre
    martèlerait le tiers exactement quand il va mal."""
    tenant, link = setup
    with use_tenant(tenant.id):
        (exchange,) = _queue(tenant, link)
        maintenant = timezone.now()
        drain_outbound_queue(tenant, sender=_always_fails(), now=maintenant)

        exchange.refresh_from_db()
        assert exchange.state == FlwExchange.STATE_TO_RETRY
        assert exchange.attempt == 1
        assert exchange.next_attempt_at == maintenant + dt.timedelta(seconds=60)

        assert due_exchanges(tenant, now=maintenant) == []
        plus_tard = maintenant + dt.timedelta(seconds=61)
        assert [e.id for e in due_exchanges(tenant, now=plus_tard)] == [exchange.id]


def test_exhausted_attempts_hold_the_exchange_instead_of_retrying_forever(setup) -> None:
    """Axe A5, « comportement au-delà : mise en attente ». L'échange reste
    visible et repris par un rejeu supervisé, jamais repris tout seul."""
    tenant, link = setup
    with use_tenant(tenant.id):
        link.max_attempts = 2
        link.breaker_threshold = 99  # on isole l'épuisement du disjoncteur
        link.save(update_fields=["max_attempts", "breaker_threshold"])
        (exchange,) = _queue(tenant, link)

        moment = timezone.now()
        for _tour in range(2):
            drain_outbound_queue(tenant, sender=_always_fails(), now=moment)
            moment += dt.timedelta(hours=2)

        exchange.refresh_from_db()
        assert exchange.attempt == 2
        assert exchange.state == FlwExchange.STATE_TO_RETRY
        assert exchange.next_attempt_at is None, (
            "Un échange dont les tentatives sont épuisées porte encore une échéance : "
            "il sera repris automatiquement, ce que la mise en attente interdit."
        )
        assert due_exchanges(tenant, now=moment + dt.timedelta(days=30)) == []


def test_exhausted_attempts_abandon_when_the_link_says_so(setup) -> None:
    """L'autre branche de l'axe A5, « abandon tracé ». Une notification de
    confort n'a plus d'objet trois jours plus tard."""
    tenant, link = setup
    with use_tenant(tenant.id):
        link.max_attempts = 1
        link.breaker_threshold = 99
        link.on_attempts_exhausted = FlwLink.EXHAUSTED_ABANDON
        link.save(update_fields=["max_attempts", "breaker_threshold", "on_attempts_exhausted"])
        (exchange,) = _queue(tenant, link)

        drain_outbound_queue(tenant, sender=_always_fails())
        exchange.refresh_from_db()
        assert exchange.state == FlwExchange.STATE_FAILED


# --- Les bornes de la passe ----------------------------------------------------


def test_the_pass_budget_stops_the_loop_and_leaves_the_rest_in_the_queue(setup) -> None:
    """Le budget de passe est la seule des trois bornes réellement
    opposable : elle arrête la boucle entre deux appels. Avec deux workers
    dans ce déploiement, c'est elle qui empêche un tiers lent de bloquer
    tout l'ERP."""
    tenant, link = setup
    with use_tenant(tenant.id):
        exchanges = _queue(tenant, link, count=5)
        horloge = iter([0.0, 0.0, 1.0, 1.0, 2.0, 99.0] + [99.0] * 20)
        sender = _always_succeeds()

        counts = drain_outbound_queue(
            tenant, sender=sender, max_pass_seconds=10, clock=lambda: next(horloge)
        )

        assert counts["budget_exhausted"] == 1
        assert len(sender.calls) < len(exchanges), "Le budget de passe n'a rien arrêté."
        restants = FlwExchange.objects.filter(tenant=tenant, state=FlwExchange.STATE_QUEUED).count()
        assert restants > 0, "Le budget a arrêté la passe mais la file est vide."


def test_the_burst_cap_bounds_how_many_calls_one_connector_takes_per_pass(setup) -> None:
    """« Parallélisme borné par adaptateur pour ne pas déclencher les
    limitations de débit du tiers » (§11). La vidange étant séquentielle
    aujourd'hui, ce plafond borne la taille de rafale — ce qui est
    précisément la protection utile contre une limitation de débit."""
    tenant, link = setup
    with use_tenant(tenant.id):
        link.connector.max_in_flight = 2
        link.connector.save(update_fields=["max_in_flight"])
        _queue(tenant, link, count=5)

        sender = _always_succeeds()
        counts = drain_outbound_queue(tenant, sender=sender)

        assert len(sender.calls) == 2, (
            f"{len(sender.calls)} appels pour un plafond de 2 : la rafale n'est pas bornée."
        )
        assert counts["skipped_cap"] == 3


def test_an_adapter_that_overruns_its_deadline_opens_an_editor_incident(setup) -> None:
    """Le délai maximal par appel ne peut pas être imposé — on n'avorte pas
    un appel bloquant en Python. Il est donc un contrat passé à
    l'adaptateur ET une mesure faite après coup. C'est cette mesure qui est
    testée : sans elle, un adaptateur qui ignore son délai le ferait pour
    toujours en silence.

    L'échange, lui, garde le sort que le tiers lui a donné — le corriger
    serait mentir sur ce qui s'est passé."""
    tenant, link = setup
    with use_tenant(tenant.id):
        (exchange,) = _queue(tenant, link)
        # started, contrôle de budget, avant l'appel, après l'appel.
        horloge = iter([0.0, 0.0, 0.0, 60.0, 60.0, 60.0])

        drain_outbound_queue(
            tenant,
            sender=_always_succeeds(),
            max_call_seconds=5,
            clock=lambda: next(horloge),
        )

        incident = FlwIncident.objects.filter(link=link, family=FlwIncident.FAMILY_EDITOR).first()
        assert incident is not None, (
            "Un adaptateur a rendu la main après 60 s pour un délai de 5 s et rien ne le signale."
        )
        assert incident.last_result_code == "delai_depasse"
        exchange.refresh_from_db()
        assert exchange.state == FlwExchange.STATE_ACCEPTED


def test_an_adapter_that_raises_does_not_kill_the_pass(setup) -> None:
    """Un adaptateur qui lève au lieu de rapporter n'a pas traduit l'erreur
    du tiers : c'est SON défaut. Le faire remonter tuerait la passe et tous
    les échanges qui la suivent."""
    tenant, link = setup
    with use_tenant(tenant.id):
        link.breaker_threshold = 99
        link.save(update_fields=["breaker_threshold"])
        exchanges = _queue(tenant, link, count=3)

        def sender(exchange, budget):
            raise RuntimeError("l'adaptateur a explosé")

        counts = drain_outbound_queue(tenant, sender=sender)

        assert counts["failed"] == 3, "La passe s'est arrêtée à la première exception."
        for exchange in exchanges:
            exchange.refresh_from_db()
            assert exchange.state == FlwExchange.STATE_TO_RETRY
        incident = FlwIncident.objects.get(link=link, family=FlwIncident.FAMILY_EDITOR)
        assert incident.occurrence_count == 3


# --- Supervision (§7.6) --------------------------------------------------------


def test_the_queue_depth_separates_waiting_due_and_held(setup) -> None:
    """Trois nombres, parce qu'un seul mentirait : une profondeur totale
    resterait élevée après réparation d'une panne et ne redescendrait
    jamais."""
    tenant, link = setup
    with use_tenant(tenant.id):
        link.max_attempts = 1
        link.breaker_threshold = 99
        link.save(update_fields=["max_attempts", "breaker_threshold"])

        # Un premier échange épuise sa tentative unique et part en attente.
        _queue(tenant, link)
        drain_outbound_queue(tenant, sender=_always_fails())
        # Deux autres arrivent ensuite et attendent leur tour.
        _queue(tenant, link, count=2)

        profondeur = outbound_queue_depth(tenant)
        assert profondeur["waiting"] == 2
        assert profondeur["due"] == 2, (
            "« dû » doit compter ce qui aurait déjà dû partir : c'est ce nombre qui "
            "monte quand la file se vide moins vite qu'elle ne se remplit."
        )
        assert profondeur["held"] == 1, (
            "L'échange mis en attente est compté avec ceux qui vont partir : la "
            "profondeur ne redescendrait jamais après une panne."
        )


def test_open_breakers_lists_half_open_links_too(setup) -> None:
    """Une liaison en période d'essai n'est pas une liaison saine : la
    masquer ferait disparaître de la supervision une panne qui dure
    précisément pendant qu'on teste si elle est finie."""
    tenant, link = setup
    with use_tenant(tenant.id):
        assert open_breakers(tenant) == []
        link.breaker_state = FlwLink.BREAKER_HALF_OPEN
        link.save(update_fields=["breaker_state"])
        assert [liaison.id for liaison in open_breakers(tenant)] == [link.id]
