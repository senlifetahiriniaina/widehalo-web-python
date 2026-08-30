"""AI2 : auto-enregistrement de la guidance statique du module `sales` dans
`core.services.ai_context_registry`, appele depuis `apps.py::ready()` —
meme patron que `reports_registration.register_reports()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Ventes : devis, commandes clients, bons de livraison et facturation "
    "(y compris a l'avancement de production), qualification automatique "
    "sur stock disponible ou achat a lancer."
)
_GUIDANCE_EN = (
    "Sales: quotations, customer orders, delivery notes and invoicing "
    "(including progress-based invoicing), with automatic qualification "
    "against available stock or a purchase to trigger."
)


def register_ai_context() -> None:
    register_context(
        "sales",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
