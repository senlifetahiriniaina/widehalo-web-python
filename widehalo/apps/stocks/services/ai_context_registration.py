"""AI2 : auto-enregistrement de la guidance statique du module `stocks`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Stocks : mouvements et valorisation des stocks, reservation "
    "automatique pour les commandes de vente, inventaires et "
    "regularisations comptables associees, controle de coherence avec la "
    "production et les livraisons."
)
_GUIDANCE_EN = (
    "Stocks: stock movements and valuation, automatic reservation for "
    "sales orders, inventories and their accounting adjustments, "
    "consistency checks against production and deliveries."
)


def register_ai_context() -> None:
    register_context(
        "stocks",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
