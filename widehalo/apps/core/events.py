"""Bus d'evenements interne — seul canal de communication asynchrone
autorise entre modules (cf. regle de couplage n°5).

Implementation complete a l'etape 9. Pour l'instant, expose l'API minimale
(`publish_event`, `subscribe`) pour que `apps.py::ready()` de chaque module
puisse s'enregistrer sans erreur d'import des l'etape 1.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

_HANDLERS: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)


Handler = Callable[[dict[str, Any]], None]


def subscribe(event_type: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _HANDLERS[event_type].append(func)
        return func

    return decorator


def publish_event(
    event_type: str, payload: dict[str, Any], *, tenant_id: str | None = None
) -> None:
    """Publie un evenement apres commit de la transaction en cours.

    Version complete (persistance EventLog, dispatch via enqueue(), retry
    avec backoff) livree a l'etape 9.
    """
    from django.db import transaction

    def _dispatch() -> None:
        for handler in _HANDLERS.get(event_type, []):
            handler({"type": event_type, "payload": payload, "tenant_id": tenant_id})

    transaction.on_commit(_dispatch)
