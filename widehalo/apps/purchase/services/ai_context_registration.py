"""AI2 : auto-enregistrement de la guidance statique du module `purchase`
dans `core.services.ai_context_registry`, appele depuis `apps.py::ready()`
— meme patron que `reports_registration.register_reports()`/
`automation_registration.register_actions()` deja etablis dans ce module."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Achats : demandes d'achat, commandes fournisseurs, reception a 3 "
    "voies (bon de commande/reception/facture), reapprovisionnement "
    "automatique et gestion des litiges fournisseur (ecart de mesure ou "
    "de qualite)."
)
_GUIDANCE_EN = (
    "Purchasing: purchase requisitions, supplier orders, 3-way matching "
    "(purchase order/receipt/invoice), automatic reordering and supplier "
    "dispute handling (measurement or quality deviation)."
)


def register_ai_context() -> None:
    register_context(
        "purchase",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
