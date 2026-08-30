"""AI2 : auto-enregistrement de la guidance statique du module `presence`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que les autres modules metier (`presence` n'avait encore
aucune fonction de `ready()`, cf. `apps.py`)."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Presence et absences : pointage des heures travaillees, gestion des "
    "conges et absences, comptes rendus d'activite (CRA), avec "
    "rapprochement automatique vers la production (module `mrp`)."
)
_GUIDANCE_EN = (
    "Presence and absences: time tracking, leave and absence management, "
    "activity reports (CRA), automatically reconciled against production "
    "(`mrp` module)."
)


def register_ai_context() -> None:
    register_context(
        "presence",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
