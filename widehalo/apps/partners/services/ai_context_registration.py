"""AI2 : auto-enregistrement de la guidance statique du module `partners`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— `partners` n'avait encore aucune fonction de `ready()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Partenaires : fiches clients, fournisseurs et contacts, partagees "
    "par tous les modules metier (ventes, achats, comptabilite, "
    "logistique), avec messagerie liee (module `chat`)."
)
_GUIDANCE_EN = (
    "Partners: customer, supplier and contact records, shared by every "
    "business module (sales, purchasing, accounting, logistics), with "
    "linked messaging (`chat` module)."
)


def register_ai_context() -> None:
    register_context(
        "partners",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
