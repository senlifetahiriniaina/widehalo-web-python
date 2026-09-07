"""S6 — le jeu fermé des huit opérations, et l'adaptateur de référence.

**Ce que ce fichier corrige, dit sans embellir.** `FlwConnector.supported_
operations` annonçait en commentaire, depuis le sprint S1, que « l'exécuteur
y lit ce qu'il a le droit de demander » et qu'« un adaptateur qui n'annonce
pas une opération ne se la verra jamais confier ». Les deux phrases étaient
fausses : le champ était un `JSONField` libre que personne ne lisait, et les
trois colonnes `operation` étaient des `CharField` libres. Cinq tests des
sprints précédents s'en servaient d'ailleurs comme d'une étiquette — « CHEZ-A »,
« CASSEE », « RELEVE » — ce qui est la preuve la plus directe qu'un champ
n'est pas contraint : ses propres tests l'utilisent pour autre chose.

C'est exactement le défaut que ce dépôt corrige partout ailleurs, et il
était ici, dans du code écrit par ce même chantier. Les six familles
d'erreur, les six transformations de correspondance et les six unités de
coût sont fermées ET gardées ; les huit opérations, non.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.adapters import reference
from apps.flows.models import FlwExchange, FlwIncident, FlwLink
from apps.flows.operations import (
    INBOUND_OPERATIONS,
    OP_DROP_FILE,
    OP_INGEST_BATCH,
    OP_INITIATE_PAYMENT,
    OP_PUBLISH_DATASET,
    OP_PUSH_DOCUMENT,
    OP_QUERY_REFERENCE,
    OP_RECEIVE_EVENT,
    OP_SUBMIT_FOR_VERDICT,
    OPERATION_CODES,
)
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import drain_outbound_queue, process_outbound_queue
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S6-OPS", name="Opérations SARL")


@pytest.fixture
def liaison_de_reference(societe):
    """Une liaison branchée sur le connecteur de RÉFÉRENCE — celui dont
    l'adaptateur est réellement enregistré depuis `apps.py::ready()`."""
    with use_tenant(societe.id):
        connecteur = FlwConnectorFactory(
            tenant=societe, code=reference.CONNECTOR_CODE, is_enabled=True
        )
        return FlwLinkFactory(
            tenant=societe, connector=connecteur, state=FlwLink.STATE_ACTIVE, breaker_threshold=99
        )


def _en_file(societe, liaison, operation=OP_PUSH_DOCUMENT, body='{"a": 1}'):
    echange = prepare_exchange(societe, liaison, operation=operation, body=body)
    transition_exchange(echange, to_state=FlwExchange.STATE_QUEUED)
    return echange


# --- Le jeu fermé, refusé à l'enregistrement ----------------------------------


def test_a_ninth_operation_is_refused_when_the_connector_is_saved(societe) -> None:
    """« Validation à l'enregistrement », comme FLX-6 pour les
    correspondances. Accepter la déclaration et échouer plus tard, à la
    première passe de vidange, déplacerait la faute d'un écran de
    configuration vers un journal nocturne."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as erreur:
        FlwConnectorFactory(tenant=societe, supported_operations=["OP1", "OP9"])
    assert "OP9" in str(erreur.value)


def test_the_same_operation_declared_twice_is_refused(societe) -> None:
    """Un SOUS-ENSEMBLE au sens du cahier n'a pas de doublon. Une liste qui
    répète OP1 laisse croire à une capacité double là où il n'y en a
    qu'une."""
    with use_tenant(societe.id), pytest.raises(ValidationError):
        FlwConnectorFactory(tenant=societe, supported_operations=["OP1", "OP1"])


def test_something_that_is_not_a_list_is_refused(societe) -> None:
    with use_tenant(societe.id), pytest.raises(ValidationError):
        FlwConnectorFactory(tenant=societe, supported_operations={"OP1": True})


def test_the_eight_canonical_operations_are_accepted(societe) -> None:
    """Le témoin. Sans lui, un validateur qui refuserait TOUT laisserait les
    trois tests ci-dessus verts — c'est le mode d'échec le plus courant
    d'une garde écrite en négatif."""
    with use_tenant(societe.id):
        connecteur = FlwConnectorFactory(
            tenant=societe, supported_operations=sorted(OPERATION_CODES)
        )
    connecteur.refresh_from_db()
    assert sorted(connecteur.supported_operations) == sorted(OPERATION_CODES)


# --- Les trois refus de `prepare_exchange` -------------------------------------


def test_an_unknown_operation_is_refused_at_preparation(societe, liaison_de_reference) -> None:
    with use_tenant(societe.id), pytest.raises(ValidationError) as erreur:
        prepare_exchange(societe, liaison_de_reference, operation="SOUMETTRE")
    assert "SOUMETTRE" in str(erreur.value)


def test_an_operation_the_connector_does_not_declare_is_refused(societe) -> None:
    """La phrase que le modèle promettait depuis S1, enfin opposable : « un
    adaptateur qui n'annonce pas une opération ne se la verra jamais
    confier »."""
    with use_tenant(societe.id):
        etroit = FlwConnectorFactory(
            tenant=societe, code="etroit", supported_operations=[OP_PUSH_DOCUMENT]
        )
        liaison = FlwLinkFactory(tenant=societe, connector=etroit, state=FlwLink.STATE_ACTIVE)
        with pytest.raises(ValidationError) as erreur:
            prepare_exchange(societe, liaison, operation=OP_DROP_FILE)
    assert "etroit" in str(erreur.value)
    assert OP_DROP_FILE in str(erreur.value)


def test_an_inbound_operation_on_an_outbound_exchange_is_refused(
    societe, liaison_de_reference
) -> None:
    """§4.1 : « une seule table d'échange porte les huit, avec un attribut
    de sens et un attribut d'opération ». Deux attributs qui se
    contredisent ne décrivent aucun échange réel — et la table les
    accepterait pourtant sans broncher."""
    with use_tenant(societe.id), pytest.raises(ValidationError):
        prepare_exchange(societe, liaison_de_reference, operation=OP_RECEIVE_EVENT)


def test_an_outbound_operation_on_an_inbound_exchange_is_refused(
    societe, liaison_de_reference
) -> None:
    with use_tenant(societe.id), pytest.raises(ValidationError):
        prepare_exchange(
            societe,
            liaison_de_reference,
            operation=OP_PUSH_DOCUMENT,
            direction=FlwExchange.DIRECTION_INBOUND,
        )


# --- L'adaptateur de référence : les six opérations sortantes ------------------


@pytest.mark.parametrize(
    "operation",
    [
        OP_PUSH_DOCUMENT,
        OP_PUBLISH_DATASET,
        OP_DROP_FILE,
        OP_SUBMIT_FOR_VERDICT,
        OP_INITIATE_PAYMENT,
        OP_QUERY_REFERENCE,
    ],
)
def test_the_reference_adapter_answers_every_outbound_operation(
    societe, liaison_de_reference, operation
) -> None:
    """Six paramétrages plutôt qu'un test unique : un test qui boucle
    s'arrête à la première opération cassée et laisse ignorer les cinq
    suivantes."""
    with use_tenant(societe.id):
        echange = _en_file(societe, liaison_de_reference, operation=operation)
        comptes = process_outbound_queue(societe)

    assert comptes["sent"] == 1, comptes
    echange.refresh_from_db()
    # `accepte` pour un accusé immédiat, `attente_verdict` pour OP4/OP5 :
    # `_settle_success` traverse toujours `emis` puis tranche.
    assert echange.state in (
        FlwExchange.STATE_ACCEPTED,
        FlwExchange.STATE_AWAITING_VERDICT,
    )
    assert echange.result_code


def test_op4_and_op5_wait_for_a_verdict_instead_of_being_accepted(
    societe, liaison_de_reference
) -> None:
    """§4.1 range OP4 en « avec verdict » et OP5 en « confirmation
    différée ». Les rendre acceptées d'emblée ferait mentir le banc d'essai
    sur la seule chose que le bloc C et le bloc D auront à gérer — et
    `awaiting_verdict` existe précisément pour ne pas confondre « le tiers
    a pris » et « le tiers a validé »."""
    with use_tenant(societe.id):
        soumission = _en_file(societe, liaison_de_reference, operation=OP_SUBMIT_FOR_VERDICT)
        reglement = _en_file(societe, liaison_de_reference, operation=OP_INITIATE_PAYMENT)
        process_outbound_queue(societe)

    for echange in (soumission, reglement):
        echange.refresh_from_db()
        assert echange.state == FlwExchange.STATE_AWAITING_VERDICT, echange.operation
        assert echange.state != FlwExchange.STATE_ACCEPTED


def test_op1_is_accepted_straight_away_and_that_is_the_witness(
    societe, liaison_de_reference
) -> None:
    """Le témoin du test précédent : si l'adaptateur mettait TOUT en attente
    de verdict, l'assertion ci-dessus resterait verte sans rien dire d'OP4
    ni d'OP5."""
    with use_tenant(societe.id):
        echange = _en_file(societe, liaison_de_reference, operation=OP_PUSH_DOCUMENT)
        process_outbound_queue(societe)
    echange.refresh_from_db()
    assert echange.state == FlwExchange.STATE_ACCEPTED


@pytest.mark.parametrize("famille", [code for code, _label in FlwIncident.FAMILY_CHOICES])
def test_the_reference_adapter_can_produce_every_error_family(
    societe, liaison_de_reference, famille
) -> None:
    """Les six familles de §10.3, exerçables sans tiers. C'est ce qui rend
    testable, aujourd'hui et sans habilitation, le comportement du
    disjoncteur, de l'espacement de réessai et des actions de reprise pour
    chacune."""
    with use_tenant(societe.id):
        liaison_de_reference.settings = {reference.SETTINGS_KEY: {"scenario": f"echec_{famille}"}}
        liaison_de_reference.save(update_fields=["settings"])
        _en_file(societe, liaison_de_reference)
        comptes = process_outbound_queue(societe)

        assert comptes["failed"] == 1, comptes
        incident = FlwIncident.objects.get(link=liaison_de_reference)
    assert incident.family == famille


def test_the_reference_adapter_never_pretends_to_send_without_time_left(
    societe, liaison_de_reference
) -> None:
    """Un budget épuisé rend un ÉCHEC, jamais un succès. Un adaptateur qui
    rendrait « accepté » sans avoir eu le temps d'appeler écrirait dans le
    registre un envoi qui n'a pas eu lieu — et le registre est une preuve,
    pas un compte rendu d'intention."""
    with use_tenant(societe.id):
        echange = _en_file(societe, liaison_de_reference)
        verdict = reference.send(echange, 0.0)
    assert verdict.ok is False
    assert verdict.family == FlwIncident.FAMILY_UNAVAILABLE


def test_an_inbound_operation_handed_to_the_outbound_path_is_an_editor_anomaly(
    societe, liaison_de_reference
) -> None:
    """Couvre les lignes écrites AVANT le refus de `prepare_exchange` : une
    migration de données, un import d'archive, un correctif à la main. La
    famille est « anomalie à signaler à l'éditeur » et non « donnée
    invalide » — c'est notre code qui a produit la ligne, pas la pièce du
    client."""
    with use_tenant(societe.id):
        echange = _en_file(societe, liaison_de_reference)
        echange.operation = OP_INGEST_BATCH  # jamais via `prepare_exchange`
        verdict = reference.send(echange, 30.0)
    assert verdict.ok is False
    assert verdict.family == FlwIncident.FAMILY_EDITOR


# --- Les deux opérations entrantes ---------------------------------------------


@pytest.mark.parametrize("operation", sorted(INBOUND_OPERATIONS))
def test_the_two_inbound_operations_write_a_traced_exchange(
    societe, liaison_de_reference, operation
) -> None:
    """« Un adaptateur qui n'écrit pas dans le registre n'est pas un
    connecteur, c'est une fuite » (décision structurante n°1). La fuite est
    plus facile à commettre du côté entrant : personne n'attend de réponse,
    donc rien ne la rend visible."""
    fonction = reference.ingest_batch if operation == OP_INGEST_BATCH else reference.receive_event
    with use_tenant(societe.id):
        echange = fonction(societe, liaison_de_reference, body='{"lignes": 3}')
        echange.refresh_from_db()

    assert echange.direction == FlwExchange.DIRECTION_INBOUND
    assert echange.operation == operation
    assert echange.payload_fingerprint, "FLX-1 : aucun échange écrit sans empreinte."
    assert echange.state == FlwExchange.STATE_SENT


def test_an_inbound_exchange_is_never_drained_by_the_outbound_pass(
    societe, liaison_de_reference
) -> None:
    """Le sens n'est pas décoratif : une notification reçue ne doit jamais
    être ré-émise vers le tiers qui nous l'a envoyée."""
    appels = []

    def _mouchard(echange, budget):
        appels.append(echange.id)
        raise AssertionError("la passe sortante a appelé pour un échange entrant")

    with use_tenant(societe.id):
        reference.receive_event(societe, liaison_de_reference, body="{}")
        drain_outbound_queue(societe, sender=_mouchard)
    assert appels == []


# --- La liaison suspendue (défaut trouvé en S6) --------------------------------


@pytest.mark.parametrize("etat", [FlwLink.STATE_DRAFT, FlwLink.STATE_SUSPENDED])
def test_a_link_that_is_not_active_is_never_drained(societe, liaison_de_reference, etat) -> None:
    """**Le défaut.** Le déclencheur événementiel et le répartiteur planifié
    refusaient déjà une liaison en brouillon ou suspendue, chacun avec son
    test. La vidange, elle, ne regardait pas : tout ce qui était DÉJÀ en
    file continuait de partir. Suspendre une liaison ne suspendait donc
    rien — alors qu'on suspend justement parce que les envois en cours
    posent problème."""
    appels = []

    def _mouchard(echange, budget):
        appels.append(echange.id)
        raise AssertionError("une liaison non active a été appelée")

    with use_tenant(societe.id):
        echange = _en_file(societe, liaison_de_reference)
        liaison_de_reference.state = etat
        liaison_de_reference.save(update_fields=["state"])
        drain_outbound_queue(societe, sender=_mouchard)

    assert appels == []
    echange.refresh_from_db()
    assert echange.state == FlwExchange.STATE_QUEUED, (
        "L'échange doit RESTER en file : l'état de la liaison peut changer, "
        "l'échange n'a pas à mourir avec."
    )


def test_the_same_exchange_leaves_once_the_link_is_reactivated(
    societe, liaison_de_reference
) -> None:
    """Le témoin du test précédent. Sans lui, une vidange qui n'appellerait
    JAMAIS personne le laisserait vert."""
    with use_tenant(societe.id):
        echange = _en_file(societe, liaison_de_reference)
        liaison_de_reference.state = FlwLink.STATE_SUSPENDED
        liaison_de_reference.save(update_fields=["state"])
        process_outbound_queue(societe)
        echange.refresh_from_db()
        assert echange.state == FlwExchange.STATE_QUEUED

        liaison_de_reference.state = FlwLink.STATE_ACTIVE
        liaison_de_reference.save(update_fields=["state"])
        process_outbound_queue(societe)
        echange.refresh_from_db()
    assert echange.state == FlwExchange.STATE_ACCEPTED
