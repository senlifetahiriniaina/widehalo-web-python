"""AUTO4 — moteur d'execution : declencheur (simule) -> condition ->
action -> tracabilite AutoRun/AutoRunStep, y compris un cas d'echec
d'action avec retry puis `partial`."""

from __future__ import annotations

import pytest

from apps.automation.models import (
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_SUCCESS,
    RUN_STEP_STATUS_FAILED,
    RUN_STEP_STATUS_SUCCESS,
    AutoFlow,
    AutoRunStep,
)
from apps.automation.services import engine
from apps.automation.services.flows import add_action_step, add_condition_step, create_flow
from apps.core.services.automation_registry import register_action
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(engine, "sleep", lambda seconds: None)


def _flow(tenant) -> AutoFlow:
    return create_flow(tenant, name="Flux test", trigger_event_type="workflow.transitioned")


def test_run_flow_single_action_success() -> None:
    calls = []
    register_action(
        code="test.engine_success",
        module="test",
        label="Success",
        function=lambda tenant_id, params: calls.append((tenant_id, params)) or {"ok": True},
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        add_action_step(
            flow,
            action_code="test.engine_success",
            param_mapping={"amount": "=payload['amount']"},
        )

        run = engine.run_flow(flow, payload={"amount": 100})
        run_step = AutoRunStep.objects.get(run=run)

    assert run.status == RUN_STATUS_SUCCESS
    assert calls == [(str(tenant.id), {"amount": 100})]
    assert run_step.status == RUN_STEP_STATUS_SUCCESS
    assert run_step.result == {"ok": True}


def test_run_flow_condition_true_branch() -> None:
    register_action(
        code="test.engine_branch",
        module="test",
        label="Branch",
        function=lambda tenant_id, params: {"branch": "true"},
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        action = add_action_step(flow, action_code="test.engine_branch")
        add_condition_step(
            flow, expression="payload['amount'] > 50", next_step=action, next_step_on_false=None
        )

        run = engine.run_flow(flow, payload={"amount": 100})
        step_count = AutoRunStep.objects.filter(run=run).count()

    assert run.status == RUN_STATUS_SUCCESS
    assert step_count == 2


def test_run_flow_condition_false_branch_skips_action() -> None:
    calls = []
    register_action(
        code="test.engine_should_not_run",
        module="test",
        label="Should not run",
        function=lambda tenant_id, params: calls.append(1),
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        action = add_action_step(flow, action_code="test.engine_should_not_run")
        add_condition_step(flow, expression="payload['amount'] > 50", next_step=action)

        run = engine.run_flow(flow, payload={"amount": 10})
        step_count = AutoRunStep.objects.filter(run=run).count()

    assert calls == []
    assert run.status == RUN_STATUS_SUCCESS
    assert step_count == 1


def test_run_flow_action_failure_retries_then_marks_partial() -> None:
    attempts = []

    def _always_fails(tenant_id, params):
        attempts.append(1)
        raise RuntimeError("boom")

    register_action(
        code="test.engine_failing", module="test", label="Failing", function=_always_fails
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        add_action_step(flow, action_code="test.engine_failing")

        run = engine.run_flow(flow, payload={})
        run_step = AutoRunStep.objects.get(run=run)

    assert len(attempts) == engine.MAX_ATTEMPTS
    assert run.status == RUN_STATUS_PARTIAL
    assert run_step.status == RUN_STEP_STATUS_FAILED
    assert run_step.retry_count == engine.MAX_ATTEMPTS


def test_run_flow_continues_after_action_failure() -> None:
    """Un flux continue vers l'etape suivante meme apres l'echec definitif
    d'une action (cf. plan) — jamais un blocage silencieux."""
    calls = []
    register_action(
        code="test.engine_always_fails_2",
        module="test",
        label="Failing",
        function=lambda tenant_id, params: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    register_action(
        code="test.engine_second_step",
        module="test",
        label="Second",
        function=lambda tenant_id, params: calls.append(1) or {"ok": True},
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        second = add_action_step(flow, action_code="test.engine_second_step")
        add_action_step(flow, action_code="test.engine_always_fails_2", next_step=second)

        run = engine.run_flow(flow, payload={})
        step_count = AutoRunStep.objects.filter(run=run).count()

    assert calls == [1]
    assert run.status == RUN_STATUS_PARTIAL
    assert step_count == 2


def test_run_flow_unregistered_action_fails_that_step_but_run_recorded() -> None:
    register_action(
        code="test.engine_will_be_deregistered",
        module="test",
        label="Temp",
        function=lambda tenant_id, params: {"ok": True},
    )
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        step = add_action_step(flow, action_code="test.engine_will_be_deregistered")
        # `add_action_step` refuse deja les codes non enregistres a la
        # CREATION — pour ce test on force un config invalide APRES coup,
        # ce qui simule une action retiree du registre entre la creation du
        # flux et son execution (cas reel : redeploiement sans cette
        # action).
        step.config = {"action_code": "test.__never_registered__"}
        step.save(update_fields=["config"])

        run = engine.run_flow(flow, payload={})
        run_step = AutoRunStep.objects.get(run=run)

    assert run.status == RUN_STATUS_PARTIAL
    assert run_step.status == RUN_STEP_STATUS_FAILED
    assert "non enregistree" in run_step.error


def test_run_flow_with_no_steps_marks_run_failed() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        flow = _flow(tenant)
        run = engine.run_flow(flow, payload={})

    assert run.status == RUN_STATUS_FAILED


def test_resolve_param_mapping_static_and_expression_values() -> None:
    resolved = engine.resolve_param_mapping(
        {"static": "value", "computed": "=payload['x'] + 1"}, {"x": 41}
    )
    assert resolved == {"static": "value", "computed": 42}
