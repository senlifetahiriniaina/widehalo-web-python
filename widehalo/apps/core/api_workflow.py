from typing import Any

from ninja import Router

from apps.core.models.workflow import ApprovalRequest
from apps.core.schemas_workflow import ApprovalDecisionIn, ApprovalRequestOut
from apps.core.services import approvals

router = Router(tags=["workflow"])

# Chantier RG-QUALIF : certaines `ApprovalRule` (qualification d'une ligne
# d'import) attendent un effet de bord APRES la decision generique
# (`approvals.decide`) — mettre a jour le statut de la ligne d'import
# metier concernee (`AccImportRow`/`StkImportRow`/`AccInvoiceImportRow`),
# jamais visible depuis `core` autrement. Registre {(app_label, model):
# callable}, resolu PARESSEUSEMENT (import local dans chaque lambda) pour
# ne jamais faire dependre le chargement de `core` de celui des apps
# metier — `core` ne peut de toute facon importer QUE `apps.<module>.
# services.public` (regle de couplage n°1), jamais un modele, donc cette
# fonction ne recoit ici que l'UUID de la demande, jamais l'objet ligne."""


def _qualification_decision_hooks() -> dict[tuple[str, str], Any]:
    from apps.accounting.services.public import (
        decide_cash_journal_qualification,
        decide_invoice_import_qualification,
    )
    from apps.stocks.services.public import decide_stock_import_qualification

    return {
        ("accounting", "accimportrow"): decide_cash_journal_qualification,
        ("accounting", "accinvoiceimportrow"): decide_invoice_import_qualification,
        ("stocks", "stkimportrow"): decide_stock_import_qualification,
    }


@router.get("/approvals/pending", response=list[ApprovalRequestOut])
def pending_approvals(request):
    requests = approvals.pending_for_user(request.auth)
    return [
        ApprovalRequestOut(
            id=str(r.id),
            rule_name=r.rule.name,
            status=r.status,
            requested_by=r.requested_by.email,
            comment=r.comment,
        )
        for r in requests
    ]


@router.post("/approvals/{request_id}/decide")
def decide_approval(request, request_id: str, payload: ApprovalDecisionIn):
    approval_request = ApprovalRequest.objects.get(id=request_id)
    approvals.decide(
        approval_request, request.auth, approved=payload.approved, comment=payload.comment
    )
    hook = _qualification_decision_hooks().get(
        (approval_request.content_type.app_label, approval_request.content_type.model)
    )
    if hook is not None:
        hook(
            approval_request.id,
            request.auth,
            approved=payload.approved,
            comment=payload.comment,
        )
    return {"status": approval_request.status}
