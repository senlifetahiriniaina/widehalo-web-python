from ninja import Router

from apps.core.models.workflow import ApprovalRequest
from apps.core.schemas_workflow import ApprovalDecisionIn, ApprovalRequestOut
from apps.core.services import approvals

router = Router(tags=["workflow"])


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
    return {"status": approval_request.status}
