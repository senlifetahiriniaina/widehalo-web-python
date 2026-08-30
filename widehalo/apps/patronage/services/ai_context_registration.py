"""AI2 : auto-enregistrement de la guidance statique du module `patronage`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Patrons et gradation : creation et gestion des patrons de coupe "
    "textile, gradation multi-tailles, lien avec les nomenclatures de "
    "production (module `mrp`)."
)
_GUIDANCE_EN = (
    "Patterns and grading: textile cutting pattern creation and "
    "management, multi-size grading, linked to production bills of "
    "materials (`mrp` module)."
)


def register_ai_context() -> None:
    register_context(
        "patronage",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
