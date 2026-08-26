"""PAT-ECO1 (enrichissement WideHalo) : le passage d'une version de patron
a la suivante declenche l'analyse d'impact sur les nomenclatures derivees
et exige une validation — meme patron que la validation de facture
accounting (A4) et la remise CRM (C2) : reutilise `ApprovalRule`/
`ApprovalRequest` du socle."""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import request_approval
from apps.mrp.services.public import list_active_boms_for_product
from apps.patronage.models import PatPattern
from apps.patronage.services.patterns import validate_pattern

RULE_NAME = "patronage.pattern_version.eco"
DEFAULT_APPROVER_ROLE = "resp_production"


class EcoApprovalRequiredError(Exception):
    """Une nouvelle version de patron impacte des nomenclatures actives —
    une validation a ete demandee (ou est deja en attente)."""


def impacted_boms(pattern: PatPattern) -> list[dict[str, object]]:
    if pattern.product_template_id is None:
        return []
    return list_active_boms_for_product(pattern.product_template_id)


def _ensure_rule(tenant: Tenant) -> ApprovalRule:
    content_type = ContentType.objects.get_for_model(PatPattern)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=RULE_NAME,
        defaults={"approver_role": DEFAULT_APPROVER_ROLE, "sequence_order": 1},
    )
    return rule


def enforce_eco_validation(pattern: PatPattern, *, requested_by: User) -> None:
    """A appeler avant de valider une nouvelle version de patron qui
    impacte des nomenclatures actives. Ne fait rien si aucune nomenclature
    active ne derive du meme produit."""
    if not impacted_boms(pattern):
        return

    rule = _ensure_rule(pattern.tenant)
    content_type = ContentType.objects.get_for_model(PatPattern)
    existing = ApprovalRequest.objects.filter(
        rule=rule, content_type=content_type, object_id=str(pattern.id)
    ).first()

    if existing is None:
        request_approval(pattern, rule, requested_by=requested_by)
        raise EcoApprovalRequiredError(
            f"Version impacte des nomenclatures actives — validation demandee a "
            f"{rule.approver_role}."
        )
    if existing.status == ApprovalRequest.STATUS_PENDING:
        raise EcoApprovalRequiredError(f"Validation en attente ({rule.approver_role}).")
    if existing.status == ApprovalRequest.STATUS_REJECTED:
        raise EcoApprovalRequiredError("Changement de version rejete par l'approbateur.")


def validate_pattern_version(pattern: PatPattern, *, requested_by: User) -> PatPattern:
    """A utiliser au lieu de `patterns.validate_pattern()` pour toute
    version qui n'est pas la premiere (RG-PAT-ECO1) : leve tant que
    l'analyse d'impact n'est pas validee par l'approbateur."""
    enforce_eco_validation(pattern, requested_by=requested_by)
    return validate_pattern(pattern)
