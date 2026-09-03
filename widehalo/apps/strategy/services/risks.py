"""Cartographie des risques d'entreprise (cahier §13.3, STR-8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.strategy.models import StgRisk

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User
    from apps.strategy.models import StgObjective


def create_risk(
    tenant: Tenant,
    *,
    title: str,
    probability: int,
    impact: int,
    description: str = "",
    control_measure: str = "",
    owner: User | None = None,
    linked_objective: StgObjective | None = None,
    created_by: User | None = None,
) -> StgRisk:
    risk = StgRisk(
        tenant=tenant,
        title=title,
        description=description,
        probability=probability,
        impact=impact,
        control_measure=control_measure,
        owner=owner,
        linked_objective=linked_objective,
        created_by=created_by,
        updated_by=created_by,
    )
    risk.full_clean()
    risk.save()
    return risk


def reassess_risk(
    risk: StgRisk,
    *,
    probability: int,
    impact: int,
    control_measure: str,
    user: User,
) -> StgRisk:
    """STR-8 : « toute réévaluation apparaît au journal d'audit » — capturé
    automatiquement par `apps.core.audit_signals` (post_save sur tout
    `BaseModel`), aucun mécanisme dédié requis ici."""
    risk.probability = probability
    risk.impact = impact
    risk.control_measure = control_measure
    risk.last_reassessed_at = timezone.now()
    risk.last_reassessed_by = user
    risk.updated_by = user
    risk.full_clean()
    risk.save(
        update_fields=[
            "probability",
            "impact",
            "control_measure",
            "last_reassessed_at",
            "last_reassessed_by",
            "updated_by",
            "updated_at",
        ]
    )
    return risk
