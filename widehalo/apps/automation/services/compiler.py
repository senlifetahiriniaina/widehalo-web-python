"""AUTO5 (chantier Studio de workflow visuel) — compilation du canevas
visuel (Drawflow, vendorise sous `static/vendor/drawflow/`) vers le graphe
EXECUTABLE `AutoStep`. C'est le point de couture architectural entre "ce
que l'utilisateur a dessine" (`AutoFlow.canvas_layout`, persiste brut,
jamais lu par le moteur) et "ce que `apps.automation.services.engine`
execute reellement" — cf. docstring de module de `apps.automation.models`.

**Format canvas attendu** (export Drawflow, `editor.export()` cote
JavaScript, cf. `templates/automation/builder.html`) : chaque noeud
Drawflow porte dans son champ `data` (JSON libre du framework, jamais
interprete par Drawflow lui-meme) une structure ecrite par notre propre JS
au moment de la creation d'un noeud depuis la palette :
- noeud condition : `{"step_type": "condition", "expression": "..."}`
- noeud action    : `{"step_type": "action", "action_code": "...",
                      "param_mapping": {...}}`
- noeud declencheur (informatif seul, jamais materialise en `AutoStep` —
  le declencheur reel du flux reste `AutoFlow.trigger_event_type`/
  `trigger_filter`, edites via un formulaire separe) :
  `{"step_type": "trigger"}`.

Les connexions Drawflow (`outputs.output_1.connections` = chemin
principal, `outputs.output_2.connections` = branche "faux", presente
uniquement en sortie d'un noeud condition) donnent
`next_step`/`next_step_on_false`."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.automation.models import STEP_TYPE_ACTION, STEP_TYPE_CONDITION, AutoFlow, AutoStep
from apps.core.services.automation_registry import get_registered_action


def compile_canvas_to_steps(flow: AutoFlow, canvas_layout: dict[str, Any]) -> list[AutoStep]:
    """Persiste `canvas_layout` BRUT sur `flow` (presentation, jamais lu
    par le moteur d'execution) PUIS recompile ENTIEREMENT le graphe
    `AutoStep` executable a partir de son contenu — remplace TOUJOURS les
    `AutoStep` existants du flux (jamais un merge incrementiel : une
    re-sauvegarde du canevas est la source de verite complete, coherent
    avec le principe "canvas_layout ET compile" du plan)."""
    nodes = _extract_nodes(canvas_layout)

    with transaction.atomic():
        flow.canvas_layout = canvas_layout
        flow.save(update_fields=["canvas_layout"])
        flow.steps.all().delete()

        created: dict[str, AutoStep] = {}
        for node_id, node in nodes.items():
            step = _create_step_from_node(flow, node)
            if step is not None:
                created[node_id] = step

        for node_id, node in nodes.items():
            step = created.get(node_id)
            if step is None:
                continue
            outputs = node.get("outputs", {})
            next_id = _first_connection_target(outputs.get("output_1"))
            next_false_id = _first_connection_target(outputs.get("output_2"))
            step.next_step = created.get(next_id) if next_id else None
            step.next_step_on_false = created.get(next_false_id) if next_false_id else None
            step.save(update_fields=["next_step", "next_step_on_false"])

    return list(created.values())


def _create_step_from_node(flow: AutoFlow, node: dict[str, Any]) -> AutoStep | None:
    data = node.get("data", {})
    step_type = data.get("step_type")

    if step_type == STEP_TYPE_ACTION:
        action_code = data.get("action_code", "")
        if get_registered_action(action_code) is None:
            raise ValidationError(
                _("Action '%(code)s' non enregistrée dans le catalogue d'automatisation.")
                % {"code": action_code}
            )
        return AutoStep.objects.create(
            tenant=flow.tenant,
            flow=flow,
            step_type=STEP_TYPE_ACTION,
            config={"action_code": action_code, "param_mapping": data.get("param_mapping", {})},
        )

    if step_type == STEP_TYPE_CONDITION:
        return AutoStep.objects.create(
            tenant=flow.tenant,
            flow=flow,
            step_type=STEP_TYPE_CONDITION,
            config={"expression": data.get("expression", "")},
        )

    # Noeud "trigger" (informatif seul) ou type inconnu (canevas encore en
    # cours d'edition) : ignore silencieusement, jamais une erreur
    # bloquante a la simple sauvegarde du layout brut ci-dessus.
    return None


def _extract_nodes(canvas_layout: dict[str, Any]) -> dict[str, Any]:
    try:
        return dict(canvas_layout["drawflow"]["Home"]["data"])
    except (KeyError, TypeError):
        return {}


def _first_connection_target(output: dict[str, Any] | None) -> str | None:
    if not output:
        return None
    connections = output.get("connections") or []
    if not connections:
        return None
    node = connections[0].get("node")
    return str(node) if node is not None else None
