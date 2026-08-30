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


# AI2 — modules metier deja construits a ce chantier (cf. plan), chacun
# devant s'auto-enregistrer depuis son propre `apps.py::ready()` (jamais un
# import direct par `apps.ai`). `chat`/`core`/`ai`/`automation` sont
# deliberement exclus (cf. docstring du prompt AI2 : `chat` est ouvert a
# tout utilisateur authentifie sans RBAC, `ai`/`automation` sont de
# l'infrastructure transverse, pas des modules metier avec un besoin de
# guidance de page au meme sens).
_EXPECTED_BUSINESS_MODULES = [
    "accounting",
    "catalog",
    "crm",
    "feasibility",
    "financing",
    "logistics",
    "mrp",
    "partners",
    "patronage",
    "payroll",
    "presence",
    "projects",
    "purchase",
    "reporting",
    "sales",
    "stocks",
    "strategy",
]


def test_all_business_modules_are_registered_at_startup() -> None:
    """Meme genre de verification que `test_automation_registry.py::
    test_core_notify_role_is_registered_at_startup` : confirme que
    `apps.py::ready()` a bien execute chaque `register_ai_context()`, deja
    charge au demarrage de Django pour la suite de tests — jamais un
    enregistrement manuel refait ici."""
    for module in _EXPECTED_BUSINESS_MODULES:
        context = get_context(module)
        assert context is not None, f"module '{module}' non enregistre dans ai_context_registry"
        assert context.static_guidance_fr
        assert context.static_guidance_en
