"""AI2 (assistant contextuel par page/action) : auto-enregistrement de la
guidance statique du module `accounting` dans le registre partage
`core.services.ai_context_registry`, appele depuis `apps.py::ready()` —
meme patron que `reports_registration.register_reports()` deja etabli dans
ce module. Aucun `context_builder` pour cette premiere passe (guidance
MODULE-level uniquement, cf. cadrage AI2)."""

from __future__ import annotations

from apps.core.services.ai_context_registry import register_context

_GUIDANCE_FR = (
    "Comptabilite generale : ecritures, plan comptable, factures clients "
    "et fournisseurs, rapprochement bancaire et cloture de periode. "
    "Gere aussi les couts d'importation (frais d'approche) affectes a la "
    "valorisation du stock et l'archivage des documents comptables (RPT-10)."
)
_GUIDANCE_EN = (
    "General accounting: journal entries, chart of accounts, customer and "
    "supplier invoices, bank reconciliation and period closing. Also "
    "handles import landed costs applied to stock valuation and archiving "
    "of accounting documents (RPT-10)."
)


def register_ai_context() -> None:
    register_context(
        "accounting",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
    )
