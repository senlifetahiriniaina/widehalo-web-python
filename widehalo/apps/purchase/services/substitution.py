"""RG-PUR-2 (substitution, PU2 du sous-sequencement `purchase` — cf.
plan) : proposer, classer par compatibilite et valider des substituts.

Une substitution `degrade` exige une validation avant d'etre utilisable
(acceptance test §5.6.7 n°2 : "Une substitution de niveau degrade sans
validation est refusee"). Reutilise le patron `ApprovalRule`/
`ApprovalRequest` du socle, exactement comme
`apps.crm.services.discounts.enforce_discount_threshold` : une
`ApprovalRule` dediee scopee sur `PurSubstitute`, une `ApprovalRequest`
journalisee par `request_approval`, et la decision de l'approbateur
transite par `apps.core.services.approvals.decide` (jamais une mutation
directe de `ApprovalRequest.status`).

Role approbateur par defaut assume (le CDC ne precise pas de role pour
cette validation) : `"acheteur"` — c'est l'acheteur, responsable de la
demande d'achat, qui valide qu'un substitut degrade est acceptable pour
la ligne concernee (a la difference de `crm.discounts` ou l'approbateur
est un responsable commercial ; ici il n'y a pas de notion hierarchique
distincte a ce stade du CDC, donc le role "metier" le plus proche est
retenu, meme discipline "documenter les defauts assumes" que le reste de
ce sous-sequencement)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import decide, request_approval
from apps.purchase.models import PurSubstitute

RULE_NAME = "purchase.substitute.degrade_validation"
DEFAULT_APPROVER_ROLE = "acheteur"

_COMPATIBILITY_ORDER = {
    PurSubstitute.COMPATIBILITY_IDENTIQUE: 0,
    PurSubstitute.COMPATIBILITY_EQUIVALENT: 1,
    PurSubstitute.COMPATIBILITY_DEGRADE: 2,
}


def create_substitute(
    *,
    tenant: Tenant,
    variant_id: UUID,
    substitute_variant_id: UUID,
    compatibility: str,
    ratio: Decimal = Decimal(1),
    conditions: str = "",
) -> PurSubstitute:
    """Cree la proposition, jamais approuvee d'office — `approved_by` reste
    `None` (seule une substitution `degrade` en a besoin, cf.
    `ensure_substitute_usable`)."""
    return PurSubstitute.objects.create(
        tenant=tenant,
        variant_id=variant_id,
        substitute_variant_id=substitute_variant_id,
        compatibility=compatibility,
        ratio=ratio,
        conditions=conditions,
    )


def list_substitutes_for_variant(variant_id: UUID) -> list[PurSubstitute]:
    """Substituts actifs d'une variante, classes par compatibilite
    (identique, puis equivalent, puis degrade — RG-PUR-2 "classees par
    compatibilite", acceptance test §5.6.7 n°1)."""
    substitutes = PurSubstitute.objects.filter(variant_id=variant_id, is_active=True)
    return sorted(substitutes, key=lambda s: _COMPATIBILITY_ORDER[s.compatibility])


def _ensure_rule(tenant: Tenant) -> ApprovalRule:
    content_type = ContentType.objects.get_for_model(PurSubstitute)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=RULE_NAME,
        defaults={"approver_role": DEFAULT_APPROVER_ROLE, "sequence_order": 1},
    )
    return rule


def request_substitute_approval(substitute: PurSubstitute, *, requested_by: User) -> None:
    """Ouvre (ou reutilise) la demande d'approbation d'un substitut
    `degrade`. Ne fait rien pour `identique`/`equivalent` (immediatement
    utilisables, pas de porte d'approbation)."""
    if substitute.compatibility != PurSubstitute.COMPATIBILITY_DEGRADE:
        return

    rule = _ensure_rule(substitute.tenant)
    content_type = ContentType.objects.get_for_model(PurSubstitute)
    existing = ApprovalRequest.objects.filter(
        rule=rule, content_type=content_type, object_id=str(substitute.id)
    ).first()
    if existing is None:
        request_approval(substitute, rule, requested_by=requested_by)


def approve_substitute(substitute: PurSubstitute, *, approved_by: User) -> PurSubstitute:
    """Action de l'approbateur : fait transiter la `ApprovalRequest`
    ouverte par `request_substitute_approval` vers `STATUS_APPROVED` via
    `apps.core.services.approvals.decide` (jamais une mutation directe de
    `ApprovalRequest.status`), puis fixe `PurSubstitute.approved_by`.

    Refuse (ValidationError, i18n) si `compatibility != "degrade"` — seule
    une substitution degrade a besoin de cette etape ; identique/equivalent
    sont deja utilisables sans validation."""
    if substitute.compatibility != PurSubstitute.COMPATIBILITY_DEGRADE:
        raise ValidationError(
            _("Seule une substitution de niveau degrade necessite une validation d'approbation.")
        )

    rule = _ensure_rule(substitute.tenant)
    content_type = ContentType.objects.get_for_model(PurSubstitute)
    request = ApprovalRequest.objects.filter(
        rule=rule, content_type=content_type, object_id=str(substitute.id)
    ).first()
    if request is None:
        request = request_approval(substitute, rule, requested_by=approved_by)
    decide(request, approved_by, approved=True)

    substitute.approved_by = approved_by
    substitute.save(update_fields=["approved_by"])
    return substitute


def ensure_substitute_usable(substitute: PurSubstitute) -> None:
    """RG-PUR-2 : "Une substitution de niveau degrade sans validation est
    refusee" (acceptance test §5.6.7 n°2). Point d'application reel de la
    regle — a appeler partout ou un substitut est propose pour etre
    assigne (pour PU2 : `requisitions.add_requisition_line`)."""
    if (
        substitute.compatibility == PurSubstitute.COMPATIBILITY_DEGRADE
        and substitute.approved_by_id is None
    ):
        raise ValidationError(
            _("Une substitution de niveau degrade non validee ne peut pas etre utilisee.")
        )
