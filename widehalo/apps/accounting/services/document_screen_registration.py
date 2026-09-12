"""T8 (bloc H, CON-1) — ou se voient les pieces de ce module.

Le journal des echanges doit renvoyer chaque ligne vers sa piece. Il ne peut
pas connaitre ce module : `apps/flows/module.py` ne declare que `core`, et
c'est structurel. C'est donc CE module qui se declare, depuis
`apps.py::ready()` — meme patron que ses rapports, ses anomalies, ses outils
de copilote et ses schemas de sortie.
"""

from __future__ import annotations

from apps.core.services.document_screens import DocumentScreen, register_document_screen


def register_document_screens() -> None:
    #: La facture. L'ECRITURE comptable n'a pas d'ecran de detail
    #: propre — c'est la facture qui la porte, et un echange comptable
    #: designe toujours la piece, jamais sa ligne.
    register_document_screen(
        DocumentScreen(
            code="accounting.AccMove",
            label="Facture client",
            url_name="accounting:detail",
            kwarg="invoice_id",
        )
    )
    #: G-2 — le budget. Son approbation passe par le moteur du socle, donc
    #: par l'ecran « Mes validations », qui resout le lien vers la piece par
    #: ce registre : sans cette declaration, l'approbateur lirait « budget »
    #: sans pouvoir l'ouvrir pour decider en connaissance de cause.
    register_document_screen(
        DocumentScreen(
            code="accounting.AccBudget",
            label="Budget",
            url_name="accounting:budget_detail",
            kwarg="budget_id",
        )
    )


__all__ = ["register_document_screens"]
