from typing import Any

from django.shortcuts import get_object_or_404
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
    from apps.purchase.services.public import decide_reordering_proposal
    from apps.stocks.services.public import decide_stock_import_qualification

    return {
        ("accounting", "accimportrow"): decide_cash_journal_qualification,
        ("accounting", "accinvoiceimportrow"): decide_invoice_import_qualification,
        ("stocks", "stkimportrow"): decide_stock_import_qualification,
        # Bloc F, F2 (FOR-12/FOR-13) : decision sur une proposition de
        # reapprovisionnement — meme patron RG-QUALIF que les 3 entrees
        # ci-dessus.
        ("purchase", "purreorderingproposal"): decide_reordering_proposal,
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
    """404 — jamais 500 — quand la demande n'appartient pas a la societe
    active.

    `ApprovalRequest.objects` passe par `TenantManager` depuis la migration
    0039 : une demande d'une AUTRE societe n'existe tout simplement plus
    pour cette requete, et un `.get()` nu remontait alors un
    `DoesNotExist` non attrape — c'est-a-dire une erreur 500 la ou la
    reponse correcte est « cette demande n'existe pas pour vous ».

    Le defaut n'etait pas visible avant : la demande etait trouvee, puis
    `approvals.decide` refusait proprement (403). Le filet a change la
    nature de l'echec, pas sa presence — et c'est le test d'isolation qui
    l'a signale, pas une relecture."""
    approval_request = get_object_or_404(ApprovalRequest, id=request_id)
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
