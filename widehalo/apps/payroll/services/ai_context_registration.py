"""AI2 : auto-enregistrement de la guidance statique du module `payroll`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Paie : calcul des bulletins de paie a partir des jours/heures "
    "travaillees et conges (module `presence`), charges sociales "
    "(CNAPS/OSTIE), IRSA, et comptabilisation automatique du lot de paie "
    "(module `accounting`)."
)
_GUIDANCE_EN = (
    "Payroll: payslip calculation from worked days/hours and leave "
    "(`presence` module), social contributions (CNAPS/OSTIE), income tax "
    "(IRSA), and automatic accounting of the payroll batch (`accounting` "
    "module)."
)


def register_ai_context() -> None:
    register_context(
        "payroll",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
