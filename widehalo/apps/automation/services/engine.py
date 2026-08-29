"""AUTO4 (chantier Studio de workflow visuel) — moteur d'execution d'un
`AutoFlow`. Parcourt le graphe `AutoStep` depuis le premier noeud (celui
qu'aucun autre `AutoStep` de ce flux ne reference), evalue les conditions
via `core.services.expr`, appelle les actions via
`core.services.automation_registry`, avec retry 3x/backoff exponentiel
(meme patron que `core.events`) et tracabilite complete
`AutoRun`/`AutoRunStep` — jamais un blocage silencieux : un `AutoRunStep`
est toujours ecrit, que l'etape reussisse ou echoue definitivement, et le
flux continue vers l'etape suivante meme apres l'echec definitif d'une
action (`AutoRun.status="partial"`, jamais un arret complet)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from django.utils import timezone

from apps.automation.models import (
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_SUCCESS,
    RUN_STEP_STATUS_FAILED,
    RUN_STEP_STATUS_SUCCESS,
    STEP_TYPE_CONDITION,
    AutoFlow,
    AutoRun,
    AutoRunStep,
    AutoStep,
)
from apps.core.models.event import EventLog
from apps.core.services.automation_registry import get_registered_action
from apps.core.services.expr import RestrictedExpressionError, safe_eval

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 4, 16)

# Injectable pour les tests (evite d'attendre reellement le backoff) — meme
# patron que `core.events.sleep`.
sleep: Callable[[float], None] = time.sleep


def find_entry_step(flow: AutoFlow) -> AutoStep | None:
    """Le premier noeud du graphe est celui qu'aucun autre `AutoStep` de ce
    flux ne reference via `next_step`/`next_step_on_false` — jamais un
    champ `is_entry` redondant a maintenir. Retourne `None` si le flux n'a
    aucune etape (flux vide, jamais construit jusqu'au bout)."""
    steps = list(flow.steps.filter(is_active=True))
    if not steps:
        return None
    referenced_ids = set()
    for step in steps:
        if step.next_step_id:
            referenced_ids.add(step.next_step_id)
        if step.next_step_on_false_id:
            referenced_ids.add(step.next_step_on_false_id)
    for step in steps:
        if step.id not in referenced_ids:
            return step
    # Graphe pathologique (boucle complete, jamais produit par le
    # compilateur AUTO5) : repli sur la premiere etape, jamais une
    # exception qui bloquerait tout le flux.
    return steps[0]


def resolve_param_mapping(param_mapping: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Chaque valeur de `param_mapping` est SOIT une valeur statique (JSON),
    SOIT une expression `core.services.expr` prefixee `"="` (ex.
    `"=payload['amount']"`), evaluee contre `{"payload": payload}` —
    convention disclosed dans `apps.automation.models.AutoStep`."""
    resolved: dict[str, Any] = {}
    for key, value in param_mapping.items():
        if isinstance(value, str) and value.startswith("="):
            resolved[key] = safe_eval(value[1:], {"payload": payload})
        else:
            resolved[key] = value
    return resolved


def _run_condition_step(run: AutoRun, step: AutoStep, payload: dict[str, Any]) -> AutoStep | None:
    run_step = AutoRunStep.objects.create(tenant=run.tenant, run=run, step=step)
    expression = step.config.get("expression", "")
    try:
        condition_result = bool(safe_eval(expression, {"payload": payload}))
    except RestrictedExpressionError as exc:
        run_step.status = RUN_STEP_STATUS_FAILED
        run_step.error = str(exc)
        run_step.save(update_fields=["status", "error"])
        # Une condition qui ne s'evalue pas est traitee comme "faux"
        # (branche next_step_on_false) — jamais un blocage silencieux de
        # tout le flux pour une seule condition mal formee.
        return step.next_step_on_false

    run_step.status = RUN_STEP_STATUS_SUCCESS
    run_step.result = {"value": condition_result}
    run_step.save(update_fields=["status", "result"])
    return step.next_step if condition_result else step.next_step_on_false


def _run_action_step(run: AutoRun, step: AutoStep, payload: dict[str, Any]) -> bool:
    """Retourne `True` si l'action a fini par reussir (au 1er essai ou
    apres retry), `False` si elle a definitivement echoue apres
    `MAX_ATTEMPTS` tentatives — dans les deux cas un `AutoRunStep` est
    ecrit avec le detail complet, jamais une boite noire."""
    config = step.config
    action_code = config.get("action_code")
    action = get_registered_action(action_code) if action_code else None
    run_step = AutoRunStep.objects.create(tenant=run.tenant, run=run, step=step)

    if action is None:
        run_step.status = RUN_STEP_STATUS_FAILED
        run_step.error = f"Action '{action_code}' non enregistree dans le catalogue."
        run_step.save(update_fields=["status", "error"])
        return False

    params = resolve_param_mapping(config.get("param_mapping", {}), payload)

    for attempt in range(MAX_ATTEMPTS):
        try:
            result = action.function(str(run.tenant_id), params)
        except Exception as exc:  # noqa: BLE001 - toute exception d'une action tierce doit etre tracee, jamais propagee brute
            run_step.retry_count = attempt + 1
            run_step.error = str(exc)
            run_step.save(update_fields=["retry_count", "error"])
            if attempt < MAX_ATTEMPTS - 1:
                sleep(BACKOFF_SECONDS[attempt])
                continue
            run_step.status = RUN_STEP_STATUS_FAILED
            run_step.save(update_fields=["status"])
            return False
        else:
            run_step.status = RUN_STEP_STATUS_SUCCESS
            run_step.result = result if isinstance(result, dict) else {"return": result}
            run_step.retry_count = attempt
            run_step.save(update_fields=["status", "result", "retry_count"])
            return True
    return False  # pragma: no cover - inatteignable, la boucle couvre deja tous les cas


def run_flow(
    flow: AutoFlow, *, payload: dict[str, Any], triggering_event: EventLog | None = None
) -> AutoRun:
    """Execute `flow` de bout en bout pour l'evenement `payload` donne —
    toujours cree un `AutoRun` (meme si le flux est vide/mal forme, marque
    alors `failed` immediatement), jamais une exception qui remonterait au
    dispatcher (`apps.automation.services.dispatch`) et casserait le
    traitement d'un AUTRE flux."""
    run = AutoRun.objects.create(tenant=flow.tenant, flow=flow, triggering_event=triggering_event)

    step = find_entry_step(flow)
    if step is None:
        run.status = RUN_STATUS_FAILED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        return run

    any_action_failed = False
    visited: set[Any] = set()
    while step is not None:
        if step.id in visited:
            # Garde-fou anti-boucle infinie (graphe pathologique, jamais
            # produit par le compilateur AUTO5) — jamais un run qui tourne
            # indefiniment.
            break
        visited.add(step.id)
        if step.step_type == STEP_TYPE_CONDITION:
            step = _run_condition_step(run, step, payload)
        else:
            if not _run_action_step(run, step, payload):
                any_action_failed = True
            step = step.next_step

    run.status = RUN_STATUS_PARTIAL if any_action_failed else RUN_STATUS_SUCCESS
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at"])
    return run
