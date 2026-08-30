"""AI2 : auto-enregistrement de la guidance statique du module `logistics`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()`."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Logistique : organisation des expeditions et du transport, suivi des "
    "operations import/export et coordination avec achats, ventes et "
    "stocks pour la livraison effective des marchandises."
)
_GUIDANCE_EN = (
    "Logistics: shipment and transport organization, import/export "
    "operations tracking, coordinated with purchasing, sales and stock "
    "for the actual delivery of goods."
)


def register_ai_context() -> None:
    register_context(
        "logistics",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
