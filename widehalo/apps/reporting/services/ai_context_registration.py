"""AI2 : auto-enregistrement de la guidance statique du module `reporting`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— `reporting` n'avait encore aucune fonction de `ready()` (cf.
`apps.py`/`module.py` : dependance declaree = "core" uniquement, meme
inversion de controle qu'ici)."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Rapports : catalogue transverse des rapports enregistres par tous "
    "les modules metier, generation a la demande ou planifiee, export "
    "(JSON/CSV/XLSX/PDF) et archivage."
)
_GUIDANCE_EN = (
    "Reports: cross-module catalogue of reports registered by every "
    "business module, on-demand or scheduled generation, export "
    "(JSON/CSV/XLSX/PDF) and archiving."
)


def register_ai_context() -> None:
    register_context(
        "reporting",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
