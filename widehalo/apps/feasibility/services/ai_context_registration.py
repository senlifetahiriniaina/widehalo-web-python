"""AI2 : auto-enregistrement de la guidance statique du module
`feasibility` dans `core.services.ai_context_registry`, appele depuis
`apps.py::ready()` — meme patron que `reports_registration.
register_reports()` deja etabli dans ce module."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Etudes de faisabilite : simulation de cout, prix et marge d'un "
    "produit ou d'un ensemble de produits hors pipeline commercial reel "
    "(hypothese, sans client/prospect), avec veille prix fournisseurs."
)
_GUIDANCE_EN = (
    "Feasibility studies: cost, price and margin simulation for a product "
    "or a set of products outside the real sales pipeline (a hypothesis, "
    "with no client/prospect), with supplier price watch."
)


def register_ai_context() -> None:
    register_context(
        "feasibility",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
