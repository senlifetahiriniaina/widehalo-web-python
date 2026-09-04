"""WA-3 (cahier Phase 2 §13.4) : bibliothèque de modèles de message avec
statut d'approbation — machine à états dédiée à une étape (cf. docstring
`WaMessageTemplate`, décision de ne PAS réutiliser `core.services.
approvals.ApprovalRule` ici)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.whatsapp.models import WaMessageTemplate

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def create_template(
    tenant: Tenant,
    *,
    code: str,
    name: str,
    category: str,
    body_text: str,
    language: str = "fr",
    variables: list[str] | None = None,
    estimated_cost_ariary: Decimal = Decimal(0),
    created_by: User | None = None,
) -> WaMessageTemplate:
    template = WaMessageTemplate(
        tenant=tenant,
        code=code,
        name=name,
        category=category,
        language=language,
        body_text=body_text,
        variables=variables or [],
        estimated_cost_ariary=estimated_cost_ariary,
        created_by=created_by,
        updated_by=created_by,
    )
    template.full_clean()
    template.save()
    return template


def submit_for_review(template: WaMessageTemplate) -> WaMessageTemplate:
    if template.status not in (WaMessageTemplate.STATUS_DRAFT, WaMessageTemplate.STATUS_REJECTED):
        raise ValidationError(_("Seul un modèle brouillon ou rejeté peut être soumis."))
    template.status = WaMessageTemplate.STATUS_PENDING_REVIEW
    template.submitted_at = timezone.now()
    template.rejection_reason = ""
    template.save(update_fields=["status", "submitted_at", "rejection_reason", "updated_at"])
    return template


def approve_template(template: WaMessageTemplate, *, user: User) -> WaMessageTemplate:
    if template.status != WaMessageTemplate.STATUS_PENDING_REVIEW:
        raise ValidationError(_("Seul un modèle en attente de validation peut être approuvé."))
    template.status = WaMessageTemplate.STATUS_APPROVED
    template.reviewed_at = timezone.now()
    template.reviewed_by = user
    template.save(update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"])
    return template


def reject_template(template: WaMessageTemplate, *, user: User, reason: str) -> WaMessageTemplate:
    if template.status != WaMessageTemplate.STATUS_PENDING_REVIEW:
        raise ValidationError(_("Seul un modèle en attente de validation peut être rejeté."))
    if not reason.strip():
        raise ValidationError(_("Le motif de rejet est obligatoire."))
    template.status = WaMessageTemplate.STATUS_REJECTED
    template.reviewed_at = timezone.now()
    template.reviewed_by = user
    template.rejection_reason = reason.strip()
    template.save(
        update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason", "updated_at"]
    )
    return template


def get_approved_template(tenant: Tenant, code: str) -> WaMessageTemplate | None:
    return WaMessageTemplate.objects.filter(
        tenant=tenant, code=code, status=WaMessageTemplate.STATUS_APPROVED, is_active=True
    ).first()


def render_body(template: WaMessageTemplate, variables: dict[str, Any]) -> str:
    """Rendu simple par substitution `{{nom}}` — jamais de moteur de gabarit
    executant du code (meme discipline que `AnMetricDefinition.formule`,
    texte descriptif, jamais executable)."""
    body = template.body_text
    for name in template.variables:
        body = body.replace(f"{{{{{name}}}}}", str(variables.get(name, "")))
    return body


__all__ = [
    "approve_template",
    "create_template",
    "get_approved_template",
    "reject_template",
    "render_body",
    "submit_for_review",
]
