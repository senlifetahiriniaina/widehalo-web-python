"""§5.11 reporting, REP4 : enregistrement de SAL-BL dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()`.
REP5 etendra ce fichier avec le reste des rapports `sales` deja construits
(SAL-DEVIS/SAL-BC/SAL-CA/...) — non legaux, sans passer par `render_and_
archive`.

`_adapter_delivery_note_pdf` resout `params["object_id"]` en `SalesOrder`
PUIS appelle `delivery_note_pdf` (nouveau, cf. `services/reports.py` —
`sales` n'avait jusqu'ici jamais eu de PDF pour SAL-BL, seulement des
lignes tabulaires)."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_delivery_note_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.reporting.services.public import render_and_archive
    from apps.sales.models import SalesOrder
    from apps.sales.services.reports import delivery_note_pdf

    order = SalesOrder.objects.get(id=params["object_id"])
    return render_and_archive(
        content_object=order, actor=actor, generate_fn=lambda: delivery_note_pdf(order)
    )


def register_reports() -> None:
    register_report(
        code="SAL-BL",
        module="sales",
        label="Bon de livraison",
        permission="sales.view_salesorder",
        render_pdf=_adapter_delivery_note_pdf,
        is_legal_document=True,
    )
