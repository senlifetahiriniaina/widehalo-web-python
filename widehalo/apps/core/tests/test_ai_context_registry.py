"""AI1 (socle module `ai`) — registre central de guidance contextuelle,
meme patron que `test_automation_registry.py`/`core.services.
reports_registry`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import (
    get_context,
    list_registered_contexts,
    register_context,
)


def test_register_and_get_context() -> None:
    register_context(
        "test_module", static_guidance_fr="Guidance FR", static_guidance_en="Guidance EN"
    )
    context = get_context("test_module")
    assert context is not None
    assert context.static_guidance_fr == "Guidance FR"
    assert context.static_guidance_en == "Guidance EN"
    assert context.context_builder is None


def test_register_is_idempotent_replaces_entry() -> None:
    register_context("test_replace", static_guidance_fr="V1", static_guidance_en="V1")
    register_context("test_replace", static_guidance_fr="V2", static_guidance_en="V2")
    context = get_context("test_replace")
    assert context is not None
    assert context.static_guidance_fr == "V2"


def test_unknown_module_returns_none() -> None:
    assert get_context("does_not_exist") is None


def test_context_builder_is_stored_and_callable() -> None:
    def _builder(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    register_context(
        "test_builder",
        static_guidance_fr="FR",
        static_guidance_en="EN",
        context_builder=_builder,
    )
    context = get_context("test_builder")
    assert context is not None
    assert context.context_builder is _builder
    assert context.context_builder("t1") == {"tenant_id": "t1"}


def test_list_registered_contexts_is_sorted_by_module() -> None:
    register_context("test_zzz", static_guidance_fr="Z", static_guidance_en="Z")
    register_context("test_aaa", static_guidance_fr="A", static_guidance_en="A")
    modules = [c.module for c in list_registered_contexts()]
    assert modules == sorted(modules)
