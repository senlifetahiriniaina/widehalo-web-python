"""RG-CRM-3 / WF-4 : une remise superieure au seuil autorise du role exige
une validation. Reutilise `ApprovalRule`/`ApprovalRequest` du socle (Lot 1,
etape 8), meme patron qu'`accounting.services.invoices` (validation a
seuils) mais a un seul niveau (le cahier des charges ne demande pas de
chaine ici, juste "une validation")."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import request_approval
from apps.crm.models import CrmLeadLine

RULE_NAME = "crm.lead_line.discount_validation"
DEFAULT_APPROVER_ROLE = "resp_commercial"


class DiscountApprovalRequiredError(Exception):
    """La remise depasse le plafond du role du demandeur ; une demande
    d'approbation a ete creee (ou est deja en attente)."""


def max_discount_for_user(user: User) -> Decimal:
    """Le plus permissif des plafonds de ses roles ; un role sans entree
    dans `settings.CRM_DISCOUNT_CAP_BY_ROLE` (ex. direction, admin) est
    considere sans plafond."""
    role_codes = set(user.groups.values_list("name", flat=True))
    caps = [cap for role, cap in settings.CRM_DISCOUNT_CAP_BY_ROLE.items() if role in role_codes]
    # Un role sans entree dans le mapping (direction, admin...) reste
    # illimite par conception — seuls les roles explicitement plafonnes
    # declenchent une validation.
    return max(caps) if caps else Decimal(100)


def _ensure_rule(tenant: Tenant) -> ApprovalRule:
    content_type = ContentType.objects.get_for_model(CrmLeadLine)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=RULE_NAME,
        defaults={"approver_role": DEFAULT_APPROVER_ROLE, "sequence_order": 1},
    )
    return rule


def enforce_discount_threshold(line: CrmLeadLine, *, requested_by: User) -> None:
    """A appeler avant de considerer une ligne remisee comme validee. Ne
    fait rien si la remise est dans le plafond du demandeur. Sinon, cree
    (ou verifie) la demande d'approbation et leve tant qu'elle n'est pas
    approuvee."""
    cap = max_discount_for_user(requested_by)
    if line.discount_pct <= cap:
        return

    rule = _ensure_rule(line.tenant)
    content_type = ContentType.objects.get_for_model(CrmLeadLine)
    existing = ApprovalRequest.objects.filter(
        rule=rule, content_type=content_type, object_id=str(line.id)
    ).first()

    if existing is None:
        request_approval(line, rule, requested_by=requested_by)
        raise DiscountApprovalRequiredError(
            f"Remise de {line.discount_pct}% superieure au plafond ({cap}%) — "
            f"validation demandee a {rule.approver_role}."
        )
    if existing.status == ApprovalRequest.STATUS_PENDING:
        raise DiscountApprovalRequiredError(
            f"Validation de remise en attente ({rule.approver_role})."
        )
    if existing.status == ApprovalRequest.STATUS_REJECTED:
        raise DiscountApprovalRequiredError("Remise rejetee par l'approbateur.")
