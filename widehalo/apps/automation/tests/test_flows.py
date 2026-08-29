"""AUTO3 — squelette app `automation` : creation d'un flux/etape validee
contre les mecanismes reels (event_type publie, action enregistree)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.automation.models import STEP_TYPE_ACTION, STEP_TYPE_CONDITION, AutoFlow, AutoStep
from apps.automation.services.flows import (
    add_action_step,
    add_condition_step,
    create_flow,
    set_flow_active,
)
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_create_flow_with_known_event_type() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(
            tenant, name="Notifier direction", trigger_event_type="workflow.transitioned"
        )

    assert isinstance(flow, AutoFlow)
    assert flow.is_active is False
    assert flow.reference


def test_create_flow_with_unknown_event_type_is_rejected() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_flow(tenant, name="Flux invalide", trigger_event_type="ceci.n_existe_pas")


def test_add_action_step_requires_registered_action() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Flux", trigger_event_type="workflow.transitioned")
        with pytest.raises(ValidationError):
            add_action_step(flow, action_code="not.registered", param_mapping={})


def test_add_action_step_with_registered_core_action() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Flux", trigger_event_type="workflow.transitioned")
        step = add_action_step(
            flow,
            action_code="core.notify_role",
            param_mapping={"role_code": "direction"},
        )

    assert isinstance(step, AutoStep)
    assert step.step_type == STEP_TYPE_ACTION
    assert step.config["action_code"] == "core.notify_role"


def test_add_condition_step_and_branching() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Flux", trigger_event_type="workflow.transitioned")
        action = add_action_step(flow, action_code="core.notify_role", param_mapping={})
        condition = add_condition_step(
            flow, expression="payload['target'] == 'confirmed'", next_step=action
        )

    assert condition.step_type == STEP_TYPE_CONDITION
    assert condition.next_step_id == action.id
    assert condition.next_step_on_false_id is None


def test_set_flow_active() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = create_flow(tenant, name="Flux", trigger_event_type="workflow.transitioned")
        assert flow.is_active is False
        flow = set_flow_active(flow, is_active=True)

    assert flow.is_active is True
