"""S6, FLX-8 — les deux surfaces du hub : charge utile archivée et message
rendu à l'utilisateur.

Le critère : « un motif ressemblant à un secret n'apparaît dans aucun
journal, aucune charge utile archivée et aucun message d'erreur affiché à
l'utilisateur. » Le journal et le rédacteur lui-même sont tenus par
`apps/core/tests/test_s6_secret_redaction.py`.

**Ce que `models.py` promettait, et qui n'existait pas.** Deux docstrings
du sprint S1 renvoyaient à ce sprint : « la garde de rédaction des secrets
(S6, FLX-8) le vérifiera au niveau des journaux » (`FlwCredential`) et
« la garde de rédaction de S6 vérifiera qu'aucun motif ressemblant à un
secret n'atterrit dans une charge utile ou un journal » (`FlwPayload`).
Aucune des deux n'existait, et `FlwExchange.result_message` comme
`FlwIncident.last_result_message` recopiaient tels quels ce que le tiers
renvoyait — or un tiers qui refuse une authentification renvoie volontiers
l'en-tête qu'il a reçu.
"""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.redaction import MASQUE
from apps.core.tests.utils import use_tenant
from apps.flows.adapters import reference
from apps.flows.models import FlwExchange, FlwIncident, FlwLink, FlwPayload
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import CallOutcome, drain_outbound_queue
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db

_SECRET = "AKIA0123456789SECRET"
_CORPS_FAUTIF = f'{{"montant": 42000, "api_key": "{_SECRET}"}}'


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S6-FLX8", name="Rédaction SARL")


@pytest.fixture
def liaison(societe):
    with use_tenant(societe.id):
        connecteur = FlwConnectorFactory(tenant=societe, code=reference.CONNECTOR_CODE)
        return FlwLinkFactory(
            tenant=societe,
            connector=connecteur,
            state=FlwLink.STATE_ACTIVE,
            breaker_threshold=99,
            max_attempts=99,
        )


# --- Surface n°2 : la charge utile ARCHIVÉE ------------------------------------


def test_a_secret_pattern_never_reaches_the_archived_payload(societe, liaison) -> None:
    """« Rédaction des secrets À L'ÉCRITURE », dans les termes exacts du
    dictionnaire du cahier (§13.2). À l'écriture, et pas à la lecture :
    rédiger à l'affichage laisserait le clair en base, où une sauvegarde,
    un export ou une requête d'exploitation le retrouveraient."""
    with use_tenant(societe.id):
        echange = prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body=_CORPS_FAUTIF)
        charge = FlwPayload.objects.get(exchange=echange)

    assert _SECRET not in charge.body
    assert MASQUE in charge.body
    assert "42000" in charge.body, "Le reste de la pièce doit survivre intact."


def test_the_fingerprint_is_the_one_of_what_really_leaves(societe, liaison) -> None:
    """**L'ordre compte, et c'est le seul piège de cette surface.** Rédiger
    APRÈS avoir calculé l'empreinte donnerait une empreinte d'un contenu
    que personne n'a jamais transmis — et l'empreinte n'existe que pour
    prouver « ce qui est réellement parti chez le tiers »."""
    with use_tenant(societe.id):
        echange = prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body=_CORPS_FAUTIF)
        charge = FlwPayload.objects.get(exchange=echange)

    assert echange.payload_fingerprint == FlwExchange.fingerprint_of(charge.body)
    assert echange.payload_fingerprint != FlwExchange.fingerprint_of(_CORPS_FAUTIF)
    assert charge.byte_size == len(charge.body.encode("utf-8")), (
        "La taille doit décrire le corps STOCKÉ, pas celui d'avant rédaction."
    )


def test_a_clean_payload_is_stored_byte_for_byte(societe, liaison) -> None:
    """Le témoin. Sans lui, une rédaction qui réécrirait TOUTES les charges
    utiles satisferait les deux tests précédents sans qu'on le voie."""
    propre = '{"montant": 42000, "reference": "FV-2026-0042"}'
    with use_tenant(societe.id):
        echange = prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body=propre)
        charge = FlwPayload.objects.get(exchange=echange)
    assert charge.body == propre
    assert echange.payload_fingerprint == FlwExchange.fingerprint_of(propre)


# --- Surface n°3 : le message rendu à l'utilisateur ----------------------------


def _echange_en_file(societe, liaison):
    echange = prepare_exchange(societe, liaison, operation=OP_PUSH_DOCUMENT, body='{"montant": 1}')
    transition_exchange(echange, to_state=FlwExchange.STATE_QUEUED)
    return echange


def test_what_the_third_party_answers_is_redacted_on_the_exchange(societe, liaison) -> None:
    """`result_message` est ce que la console de flux affichera. Un tiers
    qui refuse une authentification renvoie volontiers l'en-tête qu'il a
    reçu — c'est le chemin de fuite le plus direct, et le plus banal."""
    with use_tenant(societe.id):
        echange = _echange_en_file(societe, liaison)

        def _tiers_bavard(_echange, _budget):
            return CallOutcome(
                ok=False,
                result_code="401",
                result_message=f"refus : Authorization: Bearer {_SECRET}",
                family=FlwIncident.FAMILY_CREDENTIALS,
            )

        drain_outbound_queue(societe, sender=_tiers_bavard)
        echange.refresh_from_db()

    assert _SECRET not in echange.result_message
    assert MASQUE in echange.result_message


def test_the_incident_message_is_redacted_too(societe, liaison) -> None:
    """Deux colonnes, deux écritures, et une seule d'entre elles rédigée
    aurait suffi à tenir la fuite ouverte : l'incident est justement ce que
    l'exploitation regarde en premier."""
    with use_tenant(societe.id):
        _echange_en_file(societe, liaison)

        def _tiers_bavard(_echange, _budget):
            return CallOutcome(
                ok=False,
                result_code="401",
                result_message=f'{{"error": "bad key", "api_key": "{_SECRET}"}}',
                family=FlwIncident.FAMILY_CREDENTIALS,
            )

        drain_outbound_queue(societe, sender=_tiers_bavard)
        incident = FlwIncident.objects.get(link=liaison)

    assert _SECRET not in incident.last_result_message
    assert MASQUE in incident.last_result_message


def test_an_adapter_that_raises_never_leaks_through_its_exception(societe, liaison) -> None:
    """Le chemin oublié. L'exécuteur rattrape l'exception d'un adaptateur
    et en recopie le texte dans le registre — un texte que personne n'a
    écrit pour être lu, et qui porte donc ce que la bibliothèque HTTP a
    bien voulu y mettre.

    La rédaction précède la troncature à 2 000 caractères : l'inverse
    couperait un motif en deux et laisserait passer la moitié restante."""
    with use_tenant(societe.id):
        echange = _echange_en_file(societe, liaison)

        def _adaptateur_qui_leve(_echange, _budget):
            raise RuntimeError(f"connexion refusée par https://u:{_SECRET}@dgi.mg/api")

        drain_outbound_queue(societe, sender=_adaptateur_qui_leve)
        echange.refresh_from_db()
        incident = FlwIncident.objects.get(link=liaison)

    assert _SECRET not in echange.result_message
    assert _SECRET not in incident.last_result_message


def test_a_harmless_third_party_message_reaches_the_user_intact(societe, liaison) -> None:
    """Le témoin de cette surface. Un rédacteur trop large priverait
    l'exploitation du motif de refus — c'est-à-dire de la seule chose qui
    permette d'agir."""
    message = "facture FV-2026-0042 refusée : NIF du client absent (code 4102)"
    with use_tenant(societe.id):
        echange = _echange_en_file(societe, liaison)

        def _tiers_clair(_echange, _budget):
            return CallOutcome(
                ok=False,
                result_code="422",
                result_message=message,
                family=FlwIncident.FAMILY_INVALID_DATA,
            )

        drain_outbound_queue(societe, sender=_tiers_clair)
        echange.refresh_from_db()

    assert echange.result_message == message
