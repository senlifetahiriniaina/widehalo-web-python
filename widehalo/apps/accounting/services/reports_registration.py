"""§5.11 reporting, REP4 : enregistrement de ACC-FAC dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()`.
REP5 etendra ce fichier avec le reste des rapports `accounting` deja
construits (trial_balance/general_ledger/journal_report/...) — non legaux,
donc sans passer par `render_and_archive`.

`_adapter_invoice_pdf` resout `params["object_id"]` en `AccMove` PUIS
appelle `invoice_pdf` (deja existant, `services/reports.py`) — aucune
reimplementation, cf. plan §reporting."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_invoice_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.accounting.models import AccMove
    from apps.accounting.services.reports import invoice_pdf
    from apps.reporting.services.public import render_and_archive

    invoice = AccMove.objects.get(id=params["object_id"])
    return render_and_archive(
        content_object=invoice, actor=actor, generate_fn=lambda: invoice_pdf(invoice)
    )


def register_reports() -> None:
    register_report(
        code="ACC-FAC",
        module="accounting",
        label="Facture",
        permission="accounting.view_accmove",
        render_pdf=_adapter_invoice_pdf,
        is_legal_document=True,
    )
