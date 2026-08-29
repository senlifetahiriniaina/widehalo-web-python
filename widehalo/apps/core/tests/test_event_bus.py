from __future__ import annotations

import uuid

import pytest

from apps.core import events
from apps.core.models.event import EventLog

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(events, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _clear_handlers():
    events._HANDLERS.clear()
    events._WILDCARD_HANDLERS.clear()
    yield
    events._HANDLERS.clear()
    events._WILDCARD_HANDLERS.clear()


def test_publish_event_triggers_subscribed_handler() -> None:
    received = []

    @events.subscribe("demo.created")
    def handler(event):
        received.append(event)

    from django.db import transaction

    tenant_id = str(uuid.uuid4())
    with transaction.atomic():
        events.publish_event("demo.created", {"id": 1}, tenant_id=tenant_id)

    assert len(received) == 1
    assert received[0]["payload"] == {"id": 1}

    log = EventLog.objects.get(event_type="demo.created")
    assert log.status == EventLog.STATUS_DISPATCHED
    assert log.attempts == 1


def test_publish_event_not_dispatched_on_rollback() -> None:
    received = []

    @events.subscribe("demo.rollback")
    def handler(event):
        received.append(event)

    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        events.publish_event("demo.rollback", {"id": 2})
        raise IntegrityError("simulated rollback")

    assert received == []
    assert not EventLog.objects.filter(event_type="demo.rollback").exists()


def test_failing_handler_is_retried_three_times_then_marked_failed() -> None:
    attempts = []

    @events.subscribe("demo.failing")
    def handler(event):
        attempts.append(1)
        raise RuntimeError("boom")

    from django.db import transaction

    with transaction.atomic():
        events.publish_event("demo.failing", {})

    assert len(attempts) == events.MAX_ATTEMPTS
    log = EventLog.objects.get(event_type="demo.failing")
    assert log.status == EventLog.STATUS_FAILED
    assert log.attempts == events.MAX_ATTEMPTS


def test_subscribe_all_receives_every_event_type_alongside_specific_handlers() -> None:
    """AUTO2 : un abonne generique (`subscribe_all`) recoit TOUT evenement
    publie, quel que soit son `event_type` — SANS perturber les abonnes
    specifiques deja existants (les deux recoivent l'evenement)."""
    generic_received = []
    specific_received = []

    @events.subscribe_all
    def generic_handler(event):
        generic_received.append(event)

    @events.subscribe("demo.wildcard_specific")
    def specific_handler(event):
        specific_received.append(event)

    from django.db import transaction

    with transaction.atomic():
        events.publish_event("demo.wildcard_specific", {"id": 1})
    with transaction.atomic():
        events.publish_event("demo.wildcard_other", {"id": 2})

    assert len(generic_received) == 2
    assert {e["type"] for e in generic_received} == {
        "demo.wildcard_specific",
        "demo.wildcard_other",
    }
    assert len(specific_received) == 1
    assert specific_received[0]["type"] == "demo.wildcard_specific"


def test_subscribe_all_handler_failure_follows_same_retry_contract() -> None:
    """Un abonne generique qui echoue suit exactement le meme contrat de
    retry/backoff qu'un abonne specifique — aucun traitement d'erreur
    privilegie."""
    attempts = []

    @events.subscribe_all
    def failing_generic_handler(event):
        attempts.append(1)
        raise RuntimeError("boom generic")

    from django.db import transaction

    with transaction.atomic():
        events.publish_event("demo.wildcard_failing", {})

    assert len(attempts) == events.MAX_ATTEMPTS
    log = EventLog.objects.get(event_type="demo.wildcard_failing")
    assert log.status == EventLog.STATUS_FAILED
