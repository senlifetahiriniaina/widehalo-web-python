"""AI2 : auto-enregistrement de la guidance statique du module `financing`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()` deja etabli
dans ce module."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Financement bancaire PME : constitution d'un dossier de financement, "
    "scenario previsionnel de tresorerie base sur les ventes, achats, "
    "logistique et masse salariale projetee."
)
_GUIDANCE_EN = (
    "SME bank financing: building a financing application, cash-flow "
    "forecast scenario based on projected sales, purchasing, logistics "
    "and payroll costs."
)


def register_ai_context() -> None:
    register_context(
        "financing",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
