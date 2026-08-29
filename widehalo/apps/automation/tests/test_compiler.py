"""AUTO5 — compilation du canevas visuel (export Drawflow) vers le graphe
executable AutoStep."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.automation.models import STEP_TYPE_ACTION, STEP_TYPE_CONDITION, AutoStep
from apps.automation.services.compiler import compile_canvas_to_steps
from apps.automation.services.flows import create_flow
from apps.core.services.automation_registry import register_action
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _canvas(nodes: dict) -> dict:
    return {"drawflow": {"Home": {"data": nodes}}}


def test_compile_canvas_persists_raw_layout_and_creates_steps() -> None:
    register_action(
        code="test.compiler_action",
        module="test",
        label="Action",
        function=lambda tenant_id, params: {"ok": True},
    )
    canvas = _canvas(
        {
            "1": {
                "id": 1,
                "data": {"step_type": "condition", "expression": "payload['x'] > 1"},
                "outputs": {
                    "output_1": {"connections": [{"node": "2", "output": "input_1"}]},
                    "output_2": {"connections": []},
                },
            },
            "2": {
                "id": 2,
                "data": {
                    "step_type": "action",
                    "action_code": "test.compiler_action",
                    "param_mapping": {},
                },
                "outputs": {"output_1": {"connections": []}},
            },
        }
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Canvas", trigger_event_type="workflow.transitioned")
        steps = compile_canvas_to_steps(flow, canvas)
        flow.refresh_from_db()

        assert flow.canvas_layout == canvas
        assert len(steps) == 2
        condition_step = AutoStep.objects.get(step_type=STEP_TYPE_CONDITION, flow=flow)
        action_step = AutoStep.objects.get(step_type=STEP_TYPE_ACTION, flow=flow)

    assert condition_step.config == {"expression": "payload['x'] > 1"}
    assert condition_step.next_step_id == action_step.id
    assert condition_step.next_step_on_false_id is None
    assert action_step.config == {
        "action_code": "test.compiler_action",
        "param_mapping": {},
    }


def test_compile_canvas_rejects_unregistered_action_code() -> None:
    canvas = _canvas(
        {
            "1": {
                "id": 1,
                "data": {"step_type": "action", "action_code": "test.__does_not_exist__"},
                "outputs": {},
            },
        }
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(
            tenant, name="Canvas invalide", trigger_event_type="workflow.transitioned"
        )
        with pytest.raises(ValidationError):
            compile_canvas_to_steps(flow, canvas)


def test_compile_canvas_replaces_previous_steps_entirely() -> None:
    register_action(
        code="test.compiler_replace",
        module="test",
        label="Action",
        function=lambda tenant_id, params: {"ok": True},
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Recompile", trigger_event_type="workflow.transitioned")
        compile_canvas_to_steps(
            flow,
            _canvas(
                {
                    "1": {
                        "id": 1,
                        "data": {
                            "step_type": "action",
                            "action_code": "test.compiler_replace",
                            "param_mapping": {},
                        },
                        "outputs": {},
                    }
                }
            ),
        )
        first_count = AutoStep.objects.filter(flow=flow).count()

        compile_canvas_to_steps(flow, _canvas({}))
        second_count = AutoStep.objects.filter(flow=flow).count()

    assert first_count == 1
    assert second_count == 0


def test_compile_canvas_ignores_trigger_node() -> None:
    canvas = _canvas(
        {
            "1": {"id": 1, "data": {"step_type": "trigger"}, "outputs": {}},
        }
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Avec trigger", trigger_event_type="workflow.transitioned")
        steps = compile_canvas_to_steps(flow, canvas)

    assert steps == []


def test_compile_canvas_with_empty_layout() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Vide", trigger_event_type="workflow.transitioned")
        steps = compile_canvas_to_steps(flow, {})
        flow.refresh_from_db()

    assert steps == []
    assert flow.canvas_layout == {}
