"""AI2 : auto-enregistrement de la guidance statique du module `crm` dans
`core.services.ai_context_registry`, appele depuis `apps.py::ready()` —
meme patron que `reports_registration.register_reports()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Relation commerciale : prospects, opportunites et pipeline de vente, "
    "relances et suivi des interactions avant transformation en devis "
    "(module `sales`)."
)
_GUIDANCE_EN = (
    "Customer relationship management: prospects, sales opportunities and "
    "pipeline, follow-ups and interaction tracking before conversion into "
    "a quotation (`sales` module)."
)


def register_ai_context() -> None:
    register_context(
        "crm",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
