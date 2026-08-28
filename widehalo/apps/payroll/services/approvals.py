"""Enrichissement WideHalo "Workflow d'approbation des bulletins" (§5.10.11,
verdict Adopter) : formalise l'etat `verifiee` du workflow §5.10.7 en
circuit d'approbation EXPLICITE, en reutilisant tel quel
`core.ApprovalRule`/`ApprovalRequest`/`request_approval`/`decide` — meme
patron que partout ailleurs dans ce depot (jamais un modele
`pay_period_approval` dedie)."""

from __future__ import annotations

from uuid import UUID

from django.contrib.contenttypes.models import ContentType

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import decide, request_approval
from apps.payroll.models import PayPeriod
from apps.payroll.services.periods import verify_period

RULE_NAME_PERIOD_VERIFICATION = "Verification periode de paie"


def ensure_default_approval_rules(tenant: Tenant) -> ApprovalRule:
    """Idempotent — une seule regle par tenant : passage `en_calcul ->
    verifiee` requiert la decision du role `direction` (pilotage transverse,
    meme role que les seuils d'approbation deja mis en place dans
    `accounting`/`sales`/`purchase`)."""
    content_type = ContentType.objects.get_for_model(PayPeriod)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=RULE_NAME_PERIOD_VERIFICATION,
        defaults={"approver_role": "direction", "sequence_order": 1},
    )
    return rule


def request_period_verification(
    period: PayPeriod, user: User, *, comment: str = ""
) -> ApprovalRequest:
    """RH soumet la periode `en_calcul` a l'approbateur (`direction`) — la
    periode elle-meme ne change PAS encore d'etat ici (elle passe
    `verifiee` seulement a la decision positive, cf.
    `decide_period_verification`)."""
    rule = ensure_default_approval_rules(period.tenant)
    return request_approval(period, rule, user, comment=comment)


def decide_period_verification(
    approval_request_id: UUID | str, decided_by: User, *, approved: bool, comment: str = ""
) -> ApprovalRequest:
    """A la decision POSITIVE : effectue reellement la transition FSM
    `en_calcul -> verifiee` (`services.periods.verify_period`, qui applique
    `attempt_transition()` + `.save(update_fields=[...])`, garde-fou AST
    respecte). A la decision negative : la periode reste `en_calcul`, RH
    doit recalculer/corriger avant une nouvelle demande."""
    request = ApprovalRequest.objects.get(id=approval_request_id)
    decide(request, decided_by, approved=approved, comment=comment)
    if approved:
        period = PayPeriod.objects.get(tenant=request.rule.tenant, id=request.object_id)
        verify_period(period, decided_by)
    return request
