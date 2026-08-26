from ninja import Schema


class ApprovalRequestOut(Schema):
    id: str
    rule_name: str
    status: str
    requested_by: str
    comment: str


class ApprovalDecisionIn(Schema):
    approved: bool
    comment: str = ""
