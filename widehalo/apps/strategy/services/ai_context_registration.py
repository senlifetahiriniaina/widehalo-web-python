"""AI2 : auto-enregistrement de la guidance statique du module `strategy`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()` deja etabli
dans ce module."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Strategie et pilotage : objectifs et indicateurs cles (OKR/KPI), "
    "business plan previsionnel et suivi de la capacite de charge a 90 "
    "jours (production, presence, ventes, paie)."
)
_GUIDANCE_EN = (
    "Strategy and steering: objectives and key indicators (OKR/KPI), "
    "forward-looking business plan and 90-day workload capacity outlook "
    "(production, presence, sales, payroll)."
)


def register_ai_context() -> None:
    register_context(
        "strategy",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
