"""AI2 : auto-enregistrement de la guidance statique du module `catalog`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— `catalog` n'avait encore aucune fonction de `ready()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Catalogue : produits, variantes (taille/couleur/matiere) et "
    "attributs, prix de reference — reference partagee par la production, "
    "les ventes, les achats et les stocks."
)
_GUIDANCE_EN = (
    "Catalogue: products, variants (size/color/material) and attributes, "
    "reference pricing — a shared reference used by production, sales, "
    "purchasing and stocks."
)


def register_ai_context() -> None:
    register_context(
        "catalog",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
