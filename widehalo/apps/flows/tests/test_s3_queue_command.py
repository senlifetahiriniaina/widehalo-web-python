"""S3 — le déclencheur automatique de la file, et son amorçage.

Le registre d'adaptateurs était VIDE au sprint S3 : un test qui se serait
contenté de vérifier que la commande s'exécute sans erreur aurait été vert
pour toujours, quelle que soit sa capacité à vidanger — c'est précisément
ce que ce projet appelle un théâtre de sécurité.

On enregistrait donc un adaptateur FACTICE et on vérifiait que la commande
envoie réellement. Depuis S6 le registre porte l'adaptateur de référence,
et l'amorçage garde tout son sens : il vérifie qu'un adaptateur
QUELCONQUE, y compris un que ce fichier écrit à la main, est bien joint par
la commande.

**Pourquoi la commande existe six sprints avant son premier adaptateur.**
La leçon est écrite dans ce dépôt, dans le lot WhatsApp : `retry_failed_
messages` et son backoff existaient depuis le lot initial, avec pour seuls
déclencheurs un endpoint et un bouton — « repris automatiquement »
reposait entièrement sur quelqu'un qui pense à cliquer. Livrer la file sans
son déclencheur reproduirait ce défaut, et personne ne s'en apercevrait
avant le premier connecteur réel.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import list_scheduled_commands
from apps.core.tests.utils import use_tenant
from apps.flows.adapters import reference
from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import OP_PUSH_DOCUMENT
from apps.flows.services.adapter_registry import _ADAPTERS, list_adapters, register_adapter
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import CallOutcome, process_outbound_queue
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def registre_propre():
    """Le registre est un global de processus : le rendre à son état
    d'origine évite qu'un adaptateur factice ne fuite vers les autres
    tests. Le même piège a déjà produit un budget de rapports
    ordre-dépendant dans ce dépôt (L9)."""
    avant = dict(_ADAPTERS)
    yield
    _ADAPTERS.clear()
    _ADAPTERS.update(avant)


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="S3-CMD", name="Commande S3 SARL")
    with use_tenant(tenant.id):
        connector = FlwConnectorFactory(tenant=tenant, code="factice")
        link = FlwLinkFactory(tenant=tenant, connector=connector, state=FlwLink.STATE_ACTIVE)
        exchange = prepare_exchange(
            tenant, link, operation=OP_PUSH_DOCUMENT, body='{"exemple": true}'
        )
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
    return tenant, link, exchange


def test_the_reference_adapter_is_registered_since_s6() -> None:
    """Remplace le test d'amorçage de S3 (« le registre est vide à ce
    sprint »), qui portait dans son propre corps l'instruction de le
    retirer ici. Il l'est, et ce test le remplace plutôt que de disparaître
    sans laisser de trace : ce qui était vérifié — que le registre dit la
    vérité sur son contenu — reste vérifié, avec l'autre valeur."""
    assert reference.CONNECTOR_CODE in list_adapters()


def test_an_exchange_stays_queued_when_no_adapter_can_answer_for_it(setup) -> None:
    """Le comportement qui compte pour un connecteur SANS adaptateur —
    c'est-à-dire, depuis S6, pour tout connecteur autre que celui de
    référence : l'échange RESTE EN FILE, sans appel et sans échec. Le
    marquer en échec ferait d'un déploiement partiel une perte de données,
    et d'une montée de version un incident."""
    tenant, _link, exchange = setup
    with use_tenant(tenant.id):
        counts = process_outbound_queue(tenant)

    assert counts["skipped_no_adapter"] == 1
    assert counts["sent"] == 0
    assert counts["failed"] == 0
    exchange.refresh_from_db()
    assert exchange.state == FlwExchange.STATE_QUEUED
    assert exchange.attempt == 0


def test_the_command_really_drains_when_an_adapter_answers(setup, registre_propre) -> None:
    """L'amorçage : avec un adaptateur enregistré, la commande envoie pour
    de bon. Sans ce test, le zéro d'aujourd'hui ne prouverait rien."""
    tenant, _link, exchange = setup
    appels = []

    def adaptateur(echange, budget):
        appels.append((echange.id, budget))
        return CallOutcome(ok=True, result_code="200")

    register_adapter("factice", adaptateur)
    call_command("run_flows_queue")

    assert [identifiant for identifiant, _budget in appels] == [exchange.id]
    # Le délai reçu est celui du réglage, pas une valeur inventée par
    # l'adaptateur : c'est ce qui rend « délai maximal par appel » opposable.
    from django.conf import settings

    assert appels[0][1] == settings.FLOWS_MAX_CALL_SECONDS

    exchange.refresh_from_db()
    assert exchange.state == FlwExchange.STATE_ACCEPTED
    assert exchange.attempt == 1


def test_the_command_is_declared_in_the_schedule_registry() -> None:
    """Une commande présente sur disque mais absente du registre ne
    s'exécute jamais. La garde générale du dépôt
    (`test_scheduled_commands_declared.py`) l'attraperait ; ce test dit en
    plus à quelle CADENCE, parce qu'une file de sortie déclenchée
    quotidiennement rendrait le premier réessai utile vingt-quatre heures
    après l'échec."""
    entree = next(c for c in list_scheduled_commands() if c.code == "flows.outbound_queue")
    assert entree.command == "run_flows_queue"
    assert entree.frequency == "hourly"
