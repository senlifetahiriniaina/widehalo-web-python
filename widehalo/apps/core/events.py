"""Bus d'evenements interne — seul canal de communication asynchrone
autorise entre modules (cf. regle de couplage n°5). Un evenement est
persiste immediatement dans `core_event_log` (permet le rejeu), puis
distribue apres commit de la transaction via `core/tasks.py::enqueue()`
(Django-Q2) — jamais en synchrone dans le thread web.

Chaque module s'abonne a un `event_type` avec `@subscribe(...)`, appele
depuis son propre `apps.py::ready()` — jamais un signal Django connecte
directement d'une app a une autre (regle de couplage n°5)."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 4, 16)

# Injectable pour les tests (evite d'attendre reellement le backoff).
sleep: Callable[[float], None] = time.sleep

Handler = Callable[[dict[str, Any]], None]

_HANDLERS: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event_type: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _HANDLERS[event_type].append(func)
        return func

    return decorator


def publish_event(
    event_type: str, payload: dict[str, Any], *, tenant_id: str | None = None
) -> None:
    """Persiste l'evenement immediatement (meme transaction que le fait
    metier qui le declenche), puis programme sa distribution apres commit
    — si le commit echoue (rollback), l'evenement n'est jamais distribue."""
    from django.db import transaction

    from apps.core.models.event import EventLog

    event = EventLog.objects.create(event_type=event_type, payload=payload, tenant_id=tenant_id)

    def _schedule_dispatch() -> None:
        from apps.core.tasks import enqueue

        enqueue(dispatch_event, str(event.id))

    transaction.on_commit(_schedule_dispatch)


def dispatch_event(event_id: str) -> None:
    """Execute par Django-Q2 (jamais appele directement en dehors des
    tests — cf. publish_event). Reessaie jusqu'a MAX_ATTEMPTS fois avec
    backoff exponentiel en cas d'echec d'un handler, puis marque
    l'evenement `failed`."""
    from django.utils import timezone

    from apps.core.models.event import EventLog

    event = EventLog.objects.get(id=event_id)
    handlers = _HANDLERS.get(event.event_type, [])

    for attempt in range(MAX_ATTEMPTS):
        try:
            for handler in handlers:
                handler(
                    {
                        "type": event.event_type,
                        "payload": event.payload,
                        "tenant_id": event.tenant_id,
                    }
                )
        except Exception:
            event.attempts = attempt + 1
            event.save(update_fields=["attempts"])
            if attempt < MAX_ATTEMPTS - 1:
                sleep(BACKOFF_SECONDS[attempt])
                continue
            event.status = EventLog.STATUS_FAILED
            event.save(update_fields=["status"])
            return
        else:
            event.status = EventLog.STATUS_DISPATCHED
            event.attempts = attempt + 1
            event.dispatched_at = timezone.now()
            event.save(update_fields=["status", "attempts", "dispatched_at"])
            return
