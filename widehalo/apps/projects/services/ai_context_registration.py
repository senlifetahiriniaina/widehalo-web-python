"""AI2 : auto-enregistrement de la guidance statique du module `projects`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `automation_registration.register_actions()`/
`reports_registration.register_reports()` deja etablis dans ce module."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Gestion de projets : planification (Gantt), dependances de taches, "
    "suivi budgetaire (valeur acquise/EVM), facturation multi-modes et "
    "portail client externe en lecture seule."
)
_GUIDANCE_EN = (
    "Project management: Gantt planning, task dependencies, budget "
    "tracking (earned value/EVM), multi-mode invoicing and a read-only "
    "external client portal."
)


def register_ai_context() -> None:
    register_context(
        "projects",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
