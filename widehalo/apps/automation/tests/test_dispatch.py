"""AUTO4 — dispatch dynamique bout en bout : `core.events.publish_event`
(abonne generique `subscribe_all`, enregistre par `apps.automation.apps.py`
au demarrage de Django) -> `AutoFlow` actif correspondant -> execution ->
`AutoRun`/`AutoRunStep`. Verifie aussi qu'un flux INACTIF ou d'un
`event_type` different n'est jamais declenche, et qu'un `trigger_filter`
bloque correctement."""

from __future__ import annotations

import pytest
from django.db import transaction

from apps.automation.models import RUN_STATUS_SUCCESS, AutoRun
from apps.automation.services import dispatch, engine
from apps.automation.services.flows import add_action_step, create_flow, set_flow_active
from apps.core import events
from apps.core.services.automation_registry import register_action
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(events, "sleep", lambda seconds: None)
    monkeypatch.setattr(engine, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _clear_wildcard_handlers_except_automation():
    """`dispatch_event_to_flows` est enregistre UNE SEULE fois au demarrage
    de Django (`apps.automation.apps.py::ready()`) — jamais reenregistre
    par test. On verifie juste qu'il est bien present, sans toucher
    `core.events._WILDCARD_HANDLERS` (le vider casserait ce test ET tout
    autre test qui en depend dans la meme session)."""
    assert dispatch.dispatch_event_to_flows in events._WILDCARD_HANDLERS


def test_publish_event_triggers_active_matching_flow_end_to_end() -> None:
    calls = []
    register_action(
        code="test.dispatch_record",
        module="test",
        label="Record",
        function=lambda tenant_id, params: calls.append((tenant_id, params)) or {"ok": True},
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="E2E", trigger_event_type="workflow.transitioned")
        add_action_step(
            flow, action_code="test.dispatch_record", param_mapping={"amount": "=payload['amount']"}
        )
        set_flow_active(flow, is_active=True)

    with transaction.atomic():
        events.publish_event("workflow.transitioned", {"amount": 42}, tenant_id=str(tenant.id))

    assert calls == [(str(tenant.id), {"amount": 42})]
    with use_tenant(tenant.id):
        run = AutoRun.objects.get(flow=flow)
    assert run.status == RUN_STATUS_SUCCESS
    assert run.triggering_event is not None
    assert run.triggering_event.event_type == "workflow.transitioned"


def test_inactive_flow_is_never_triggered() -> None:
    calls = []
    register_action(
        code="test.dispatch_inactive",
        module="test",
        label="Should not run",
        function=lambda tenant_id, params: calls.append(1),
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Inactif", trigger_event_type="workflow.transitioned")
        add_action_step(flow, action_code="test.dispatch_inactive")
        # jamais active

    with transaction.atomic():
        events.publish_event("workflow.transitioned", {}, tenant_id=str(tenant.id))

    assert calls == []
    with use_tenant(tenant.id):
        assert not AutoRun.objects.filter(flow=flow).exists()


def test_flow_with_different_event_type_is_never_triggered() -> None:
    calls = []
    register_action(
        code="test.dispatch_wrong_type",
        module="test",
        label="Should not run",
        function=lambda tenant_id, params: calls.append(1),
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Autre type", trigger_event_type="chat.message_created")
        add_action_step(flow, action_code="test.dispatch_wrong_type")
        set_flow_active(flow, is_active=True)

    with transaction.atomic():
        events.publish_event("workflow.transitioned", {}, tenant_id=str(tenant.id))

    assert calls == []


def test_trigger_filter_blocks_when_condition_is_false() -> None:
    calls = []
    register_action(
        code="test.dispatch_filtered",
        module="test",
        label="Should not run",
        function=lambda tenant_id, params: calls.append(1),
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(
            tenant,
            name="Filtre",
            trigger_event_type="workflow.transitioned",
            trigger_filter={"expression": "payload['amount'] > 1000"},
        )
        add_action_step(flow, action_code="test.dispatch_filtered")
        set_flow_active(flow, is_active=True)

    with transaction.atomic():
        events.publish_event("workflow.transitioned", {"amount": 10}, tenant_id=str(tenant.id))

    assert calls == []


def test_trigger_filter_allows_when_condition_is_true() -> None:
    calls = []
    register_action(
        code="test.dispatch_filtered_ok",
        module="test",
        label="Should run",
        function=lambda tenant_id, params: calls.append(1),
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(
            tenant,
            name="Filtre OK",
            trigger_event_type="workflow.transitioned",
            trigger_filter={"expression": "payload['amount'] > 1000"},
        )
        add_action_step(flow, action_code="test.dispatch_filtered_ok")
        set_flow_active(flow, is_active=True)

    with transaction.atomic():
        events.publish_event("workflow.transitioned", {"amount": 5000}, tenant_id=str(tenant.id))

    assert calls == [1]


def test_event_without_tenant_id_never_triggers_any_flow() -> None:
    """`AutoFlow` appartient toujours a un tenant — un evenement sans
    `tenant_id` (parametre optionnel de `publish_event`) ne peut jamais en
    declencher un, jamais une exception."""
    dispatch.dispatch_event_to_flows(
        {"type": "workflow.transitioned", "payload": {}, "tenant_id": None}
    )
