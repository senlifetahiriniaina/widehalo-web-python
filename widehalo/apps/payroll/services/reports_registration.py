"""§5.11 reporting, REP4 : enregistrement de PAY-BULL dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()`.
REP5 n'a rien a ajouter pour `payroll` au-dela de PAY-BULL — c'est le seul
rapport PDF/tabulaire construit par ce module (les declarations/controles
§5.10.11 ne sont pas des rapports au sens RPT-2)."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_payslip_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.payroll.models import PayPayslip
    from apps.payroll.services.pdf import payslip_pdf
    from apps.reporting.services.public import render_and_archive

    payslip = PayPayslip.objects.get(id=params["object_id"])
    return render_and_archive(
        content_object=payslip, actor=actor, generate_fn=lambda: payslip_pdf(payslip)
    )


def register_reports() -> None:
    register_report(
        code="PAY-BULL",
        module="payroll",
        label="Bulletin de paie",
        permission="payroll.view_paypayslip",
        render_pdf=_adapter_payslip_pdf,
        is_legal_document=True,
    )
