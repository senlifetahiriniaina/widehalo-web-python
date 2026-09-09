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
    #: L'opportunite.
    register_document_screen(
        DocumentScreen(
            code="crm.CrmLead", label="Opportunite", url_name="crm:detail", kwarg="lead_id"
        )
    )


__all__ = ["register_document_screens"]
