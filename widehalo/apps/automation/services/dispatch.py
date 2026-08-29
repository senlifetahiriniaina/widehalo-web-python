"""AUTO4 (chantier Studio de workflow visuel) — abonne GENERIQUE du bus
d'evenements (`core.events.subscribe_all`), enregistre UNE SEULE fois
depuis `apps.py::ready()` (cf. plan). Interroge les `AutoFlow` actifs
correspondant a l'`event_type` recu, evalue `trigger_filter` si present,
puis enqueue l'execution de chaque flux concerne via
`core.tasks.enqueue()` — jamais en synchrone dans le handler, meme
discipline que `core.events` lui-meme (le handler d'un abonne generique
doit rester rapide : il ne fait QUE filtrer et enqueuer, jamais executer
le flux directement).

**Point d'attention RLS important** : ce handler et la tache Django-Q2
qu'il enqueue s'executent HORS contexte de requete HTTP (jamais de
`TenantMiddleware` pour positionner la session Postgres) — `AutoFlow`
herite de `BaseModel`, donc protege par Row-Level Security
(`apply_rls.py`). Toute requete sur `AutoFlow`/`AutoStep`/`AutoRun`/
`AutoRunStep` DOIT donc etre executee a l'interieur d'un bloc
`apps.core.tenant_context.activate_tenant(tenant_id)` — exactement l'usage
que sa docstring annonce explicitement ("tache Django-Q2"), jamais un
contournement RLS ad hoc invente ici."""

from __future__ import annotations

from typing import Any

from apps.core.services.expr import RestrictedExpressionError, safe_eval


def dispatch_event_to_flows(event: dict[str, Any]) -> None:
    """Appele pour CHAQUE evenement publie (abonne generique), quel que
    soit son `event_type` — c'est precisement le probleme que
    `subscribe_all` resout (aucun `@subscribe(event_type)` a ecrire a
    l'avance pour un flux configure dynamiquement par un utilisateur)."""
    from apps.automation.models import AutoFlow
    from apps.core.tasks import enqueue
    from apps.core.tenant_context import activate_tenant

    event_type = event["type"]
    payload = event["payload"]
    tenant_id = event.get("tenant_id")
    event_id = event.get("id")

    if not tenant_id:
        # Tout AutoFlow appartient necessairement a un tenant (BaseModel) —
        # un evenement publie sans tenant_id (parametre optionnel de
        # `core.events.publish_event`) ne peut jamais en declencher un.
        return

    with activate_tenant(tenant_id):
        matching_flow_ids = [
            str(flow.id)
            for flow in AutoFlow.objects.filter(trigger_event_type=event_type, is_active=True)
            if _passes_trigger_filter(flow.trigger_filter, payload)
        ]

    for flow_id in matching_flow_ids:
        enqueue(execute_flow_for_event, flow_id, payload, event_id, tenant_id)


def _passes_trigger_filter(trigger_filter: dict[str, Any], payload: dict[str, Any]) -> bool:
    expression = (trigger_filter or {}).get("expression")
    if not expression:
        return True
    try:
        return bool(safe_eval(expression, {"payload": payload}))
    except RestrictedExpressionError:
        # Un filtre invalide ne declenche JAMAIS le flux (deny-by-default)
        # et ne casse jamais le dispatch des AUTRES flux concurrents
        # declenches par le meme evenement.
        return False


def execute_flow_for_event(
    flow_id: str, payload: dict[str, Any], event_id: str | None, tenant_id: str
) -> None:
    """Execute par Django-Q2 (enqueue depuis `dispatch_event_to_flows`,
    jamais appele directement en dehors des tests). `tenant_id` est
    transmis explicitement (jamais redecouvert en lisant `AutoFlow` sans
    contexte, ce qui echouerait sous RLS — cf. docstring de module) pour
    pouvoir activer le contexte tenant AVANT la premiere requete."""
    from apps.automation.models import AutoFlow
    from apps.automation.services.engine import run_flow
    from apps.core.models.event import EventLog
    from apps.core.tenant_context import activate_tenant

    with activate_tenant(tenant_id):
        flow = AutoFlow.objects.get(id=flow_id)
        triggering_event = EventLog.objects.filter(id=event_id).first() if event_id else None
        run_flow(flow, payload=payload, triggering_event=triggering_event)
