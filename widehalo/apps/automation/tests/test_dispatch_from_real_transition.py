"""Le chemin réel : une transition de workflow déclenche-t-elle un flux ?

**Ce que les six tests d'`automation` ne vérifiaient pas.** Ils publient
tous `workflow.transitioned` **eux-mêmes**, avec un `tenant_id` explicite —
ils exercent donc le dispatch, jamais son producteur. Or le producteur,
`apps/core/workflows.py`, ne renseignait aucune société ; et
`dispatch.dispatch_event_to_flows` sort immédiatement quand elle manque.
**Aucun `AutoFlow` branché sur une transition ne pouvait donc se
déclencher**, alors que `projects/services/automation_registration.py`
documente exactement ce cas ("quand une tâche est terminée").

Six tests verts, une fonctionnalité inerte. C'est le même motif que le test
BI-4 corrigé au lot L9 : vert parce qu'il court-circuite le chemin qu'il
prétend couvrir.

Ce fichier ne publie donc **jamais** d'événement lui-même. Il fait
transiter un vrai modèle par `attempt_transition`, et regarde ce qui
arrive au bout.
"""

from __future__ import annotations

import pytest

from apps.automation.models import RUN_STATUS_SUCCESS, AutoRun
from apps.automation.services import dispatch, engine
from apps.automation.services.flows import add_action_step, create_flow, set_flow_active
from apps.core import events
from apps.core.services.automation_registry import register_action
from apps.core.services.workflow import attempt_transition
from apps.core.tests.factories import TenantFactory
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(events, "sleep", lambda seconds: None)
    monkeypatch.setattr(engine, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _the_generic_subscriber_is_registered():
    assert dispatch.dispatch_event_to_flows in events._WILDCARD_HANDLERS


def _flux_branche_sur_les_transitions(tenant, *, code_action: str, appels: list):
    """Un flux actif qui écoute `workflow.transitioned` et n'enregistre que
    les passages à l'état `submitted`."""
    register_action(
        code=code_action,
        module="test",
        label="Trace la transition",
        function=lambda tenant_id, params: appels.append((tenant_id, params)) or {"ok": True},
    )
    flow = create_flow(
        tenant,
        name="Sur transition",
        trigger_event_type="workflow.transitioned",
        trigger_filter={"expression": "payload['target'] == 'submitted'"},
    )
    add_action_step(
        flow,
        action_code=code_action,
        param_mapping={"cible": "=payload['target']", "objet": "=payload['object_id']"},
    )
    set_flow_active(flow, is_active=True)
    return flow


def test_a_real_transition_triggers_the_flow_branched_on_it() -> None:
    """**Le test qui manquait.** Aucune publication d'événement dans ce
    corps : on fait transiter une vraie ligne, et le flux doit s'exécuter.

    Il rougissait avant la correction — `publish_event` ne portait pas de
    société, `dispatch_event_to_flows` sortait à la première ligne, et
    `appels` restait vide."""
    appels: list = []
    tenant = TenantFactory()

    with use_tenant(tenant.id):
        _flux_branche_sur_les_transitions(
            tenant, code_action="test.transition_reelle", appels=appels
        )
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=tenant, label="dossier")

    # La transition, et RIEN d'autre. La distribution part sur le `on_commit`
    # de `publish_event`, donc à la sortie du bloc atomique d'`use_tenant`.
    with use_tenant(tenant.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    assert appels == [(str(tenant.id), {"cible": "submitted", "objet": str(enregistrement.id)})], (
        "Une transition réelle n'a déclenché aucun flux. C'est le défaut que "
        "ce fichier existe pour couvrir : `apps/core/workflows.py` publiait "
        "`workflow.transitioned` sans société, et `dispatch_event_to_flows` "
        "écarte tout événement qui n'en porte pas."
    )

    with use_tenant(tenant.id):
        execution = AutoRun.objects.get()
    assert execution.status == RUN_STATUS_SUCCESS
    assert execution.triggering_event.event_type == "workflow.transitioned"
    assert str(execution.triggering_event.tenant_id) == str(tenant.id), (
        "L'événement journalisé ne nomme pas la société : le flux ne s'est "
        "déclenché que par accident."
    )


def test_a_transition_never_triggers_another_company_s_flow() -> None:
    """La contrepartie, et le témoin que la société transportée est bien
    LUE.

    Sans ce test, faire porter à l'événement une société constante
    quelconque suffirait à faire passer le premier. Ici la société B a un
    flux identique, et la transition a lieu chez A."""
    appels_a: list = []
    appels_b: list = []
    societe_a = TenantFactory()
    societe_b = TenantFactory()

    with use_tenant(societe_a.id):
        _flux_branche_sur_les_transitions(
            societe_a, code_action="test.transition_a", appels=appels_a
        )
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe_a, label="chez A")
    with use_tenant(societe_b.id):
        _flux_branche_sur_les_transitions(
            societe_b, code_action="test.transition_b", appels=appels_b
        )

    with use_tenant(societe_a.id):
        attempt_transition(enregistrement, "submit", None)
        enregistrement.save(update_fields=["state"])

    assert len(appels_a) == 1, "Le flux de la société propriétaire ne s'est pas déclenché."
    assert appels_b == [], (
        "Une transition chez A a déclenché le flux de B : la société portée "
        "par l'événement n'est pas celle de la ligne qui a transité."
    )


def test_the_company_comes_from_the_row_not_from_the_ambient_context() -> None:
    """Quelle des deux sources fait foi.

    `_tenant_id_of` lit d'abord `instance.tenant_id`, et seulement ensuite
    le contexte ambiant. L'ordre inverse serait indétectable dans les deux
    tests précédents — la ligne et le contexte y coïncident toujours, comme
    sous RLS en exploitation.

    On les dissocie ici de la seule façon possible : le contexte de B, une
    ligne de A. C'est une situation qu'une requête HTTP ne produit jamais
    (la RLS l'interdirait), mais qu'une commande d'administration ou une
    tâche de fond peut produire — et l'événement doit alors nommer la
    société de la LIGNE."""
    from apps.core.models.event import EventLog

    societe_a = TenantFactory()
    societe_b = TenantFactory()
    with use_tenant(societe_a.id):
        enregistrement = SampleTenantScopedRecord.objects.create(tenant=societe_a, label="chez A")

    with use_tenant(societe_b.id):
        # `save()` est volontairement omis : il échouerait sous la RLS de B.
        # Le signal `post_transition` a déjà tout publié.
        attempt_transition(enregistrement, "submit", None)

    evenement = EventLog.objects.filter(event_type="workflow.transitioned").latest("created_at")
    assert str(evenement.tenant_id) == str(societe_a.id), (
        "L'événement porte la société du CONTEXTE et non celle de la ligne : "
        "une tâche de fond attribuerait la transition à la mauvaise société."
    )
