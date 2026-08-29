"""AUTO3 — registre central des actions declenchables par un flux
d'automatisation, meme patron que `test_reports_registry` (si present) /
`core.services.reports_registry`."""

from __future__ import annotations

from apps.core.services.automation_registry import (
    get_registered_action,
    list_registered_actions,
    register_action,
)


def _noop(tenant_id: str, params: dict) -> str:  # noqa: ANN001
    return f"{tenant_id}:{params}"


def test_register_and_get_action() -> None:
    register_action(code="test.noop", module="test", label="No-op", function=_noop)
    action = get_registered_action("test.noop")
    assert action is not None
    assert action.module == "test"
    assert action.function is _noop


def test_register_is_idempotent_replaces_entry() -> None:
    register_action(code="test.replace", module="test", label="V1", function=_noop)
    register_action(code="test.replace", module="test", label="V2", function=_noop)
    action = get_registered_action("test.replace")
    assert action is not None
    assert action.label == "V2"


def test_unknown_action_returns_none() -> None:
    assert get_registered_action("does.not.exist") is None


def test_core_notify_role_is_registered_at_startup() -> None:
    """`core.notify_role` (le builtin, cf. `apps.core.services.
    automation_actions`) doit toujours etre present — enregistre depuis
    `apps.core.apps.py::ready()`, deja execute au chargement de Django
    pour la suite de tests."""
    action = get_registered_action("core.notify_role")
    assert action is not None
    assert action.module == "core"


def test_list_registered_actions_is_sorted_by_code() -> None:
    register_action(code="test.zzz", module="test", label="Z", function=_noop)
    register_action(code="test.aaa", module="test", label="A", function=_noop)
    codes = [a.code for a in list_registered_actions()]
    assert codes == sorted(codes)
