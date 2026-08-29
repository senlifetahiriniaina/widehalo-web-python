"""Bus d'evenements interne — seul canal de communication asynchrone
autorise entre modules (cf. regle de couplage n°5). Un evenement est
persiste immediatement dans `core_event_log` (permet le rejeu), puis
distribue apres commit de la transaction via `core/tasks.py::enqueue()`
(Django-Q2) — jamais en synchrone dans le thread web.

Chaque module s'abonne a un `event_type` avec `@subscribe(...)`, appele
depuis son propre `apps.py::ready()` — jamais un signal Django connecte
directement d'une app a une autre (regle de couplage n°5).

**AUTO2 (chantier Studio de workflow visuel)** : `subscribe_all(handler)`
est une extension MINIMALE et RETROCOMPATIBLE de ce bus, ajoutee pour un
besoin different de `@subscribe(event_type)` — celui-ci suppose un
developpeur qui code d'avance, dans `ready()`, l'`event_type` exact qui
l'interesse ; le studio d'automatisation a au contraire besoin de recevoir
TOUS les evenements publies, quel que soit leur `event_type`, pour
dispatcher dynamiquement vers les `AutoFlow` actifs configures par un
utilisateur (jamais connus a l'ecriture du code). Un abonne generique est
appele EN PLUS des abonnes specifiques de `dispatch_event` (jamais a leur
place), avec le meme contrat de retry/backoff — un abonne generique qui
leve une exception retarde/echoue exactement comme un abonne specifique,
il n'a aucun traitement d'erreur privilegie."""

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

# AUTO3 (chantier Studio de workflow visuel) : catalogue DECLARATIF des
# `event_type` reellement publies quelque part dans le code (verifie par
# grep sur les appels `publish_event(...)` au moment de l'ecriture,
# jamais une deduction dynamique) — sert UNIQUEMENT a valider
# `AutoFlow.trigger_event_type` a la creation d'un flux (jamais une chaine
# libre non verifiee, cf. plan) pour eviter qu'un flux reste
# silencieusement mort (abonne a un `event_type` qui ne sera jamais
# publie). A COMPLETER manuellement par le developpeur a chaque nouveau
# site d'appel `publish_event(...)` — ce n'est pas un mecanisme
# d'enregistrement automatique comme `@subscribe`.
PUBLISHED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "workflow.transitioned",  # apps/core/workflows.py — toute transition FSM, tous modules
        "notification.created",  # apps/core/services/notifications.py
        "chat.message_created",  # apps/chat/services/messaging.py
        "risk.flagged",  # apps/core/services/risk.py — RiskItem de score eleve (RSK1-2)
    }
)

_HANDLERS: dict[str, list[Handler]] = defaultdict(list)

# AUTO2 : abonnes "wildcard", recoivent TOUT evenement publie quel que soit
# son `event_type` — liste distincte de `_HANDLERS`, jamais fusionnee dans
# le dict par cle (un abonne generique n'appartient a aucun `event_type`
# en particulier).
_WILDCARD_HANDLERS: list[Handler] = []


def subscribe(event_type: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _HANDLERS[event_type].append(func)
        return func

    return decorator


def subscribe_all(handler: Handler) -> Handler:
    """Enregistre `handler` comme abonne GENERIQUE, appele pour chaque
    evenement publie quel que soit son `event_type` — a l'inverse de
    `subscribe(event_type)`, s'utilise directement comme decorateur SANS
    parametre (`@subscribe_all`), puisqu'il n'y a pas d'`event_type` a
    fournir. Appele depuis `apps.py::ready()`, comme `subscribe()` — jamais
    un signal Django connecte directement d'une app a une autre (regle de
    couplage n°5). `apps.automation` (Studio de workflow visuel) est
    concu pour n'enregistrer qu'UN SEUL abonne generique
    (`dispatch_event_to_flows`) ; rien n'empeche techniquement d'en
    enregistrer plusieurs si un futur besoin le justifie."""
    _WILDCARD_HANDLERS.append(handler)
    return handler


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
    # AUTO2 : les abonnes generiques (`subscribe_all`) recoivent l'evenement
    # EN PLUS des abonnes specifiques de cet `event_type` — meme liste,
    # meme boucle de retry, aucun traitement d'erreur privilegie pour l'un
    # ou l'autre type d'abonne.
    handlers = [*_HANDLERS.get(event.event_type, []), *_WILDCARD_HANDLERS]

    for attempt in range(MAX_ATTEMPTS):
        try:
            for handler in handlers:
                handler(
                    {
                        # AUTO4 (chantier Studio de workflow visuel) :
                        # "id" ajoute pour que `apps.automation.services.
                        # dispatch.dispatch_event_to_flows` puisse relier
                        # l'`AutoRun` qu'il declenche a l'`EventLog` reel
                        # (`AutoRun.triggering_event`) — champ additif,
                        # aucun abonne existant ne s'attend a un dict
                        # fige (verifie par la suite `test_event_bus.py`
                        # qui n'accede qu'aux cles dont il a besoin).
                        "id": str(event.id),
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
