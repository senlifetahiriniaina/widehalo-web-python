"""Pack de revue de performance (cahier §13.3, STR-7) — génération figée
et horodatée : « affiche exactement les mêmes valeurs, les mêmes
définitions et les mêmes commentaires qu'à sa génération » à toute
réouverture ultérieure."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.strategy.models import StgObjective, StgReviewPack, StgRisk
from apps.strategy.services.budget import can_close_review, compute_variance, serialize_variance_row

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User
    from apps.strategy.models import StgBudget


def _snapshot_objectives(tenant: Tenant, user: User) -> list[dict[str, Any]]:
    from apps.analytics.services.public import get_metric_definition

    rows = []
    for objective in StgObjective.objects.filter(tenant=tenant, is_active=True):
        key_results = []
        for kr in objective.key_results.filter(is_active=True):
            definition = get_metric_definition(tenant, kr.metric_code) if kr.metric_code else None
            key_results.append(
                {
                    "metric_name": kr.metric_name,
                    "metric_code": kr.metric_code,
                    # Definition figee AU MOMENT de la generation — meme si
                    # l'indicateur evolue (nouvelle version, cf. BI-9) apres
                    # coup, ce pack ne bougera jamais (STR-7).
                    "metric_definition": (
                        {
                            "libelle": definition["libelle"],
                            "formule": definition["formule"],
                            "version": definition["version"],
                        }
                        if definition
                        else None
                    ),
                    "target_value": str(kr.target_value),
                    "current_value": str(kr.current_value),
                    "progress_pct": str(kr.progress_pct()),
                }
            )
        rows.append(
            {
                "objective_id": str(objective.id),
                "title": objective.title,
                "level": objective.level,
                "status": objective.status,
                "key_results": key_results,
            }
        )
    return rows


def _snapshot_risks(tenant: Tenant) -> list[dict[str, Any]]:
    return [
        {
            "title": risk.title,
            "probability": risk.probability,
            "impact": risk.impact,
            "risk_score": risk.risk_score,
            "control_measure": risk.control_measure,
            "owner_email": risk.owner.email if risk.owner else "",
            "last_reassessed_at": (
                risk.last_reassessed_at.isoformat() if risk.last_reassessed_at else None
            ),
        }
        for risk in StgRisk.objects.filter(tenant=tenant, is_active=True)
    ]


def generate_review_pack(
    tenant: Tenant,
    *,
    budget: StgBudget | None,
    period_start: Any,
    period_end: Any,
    user: User,
    threshold_pct: Decimal = Decimal(10),
) -> StgReviewPack:
    """STR-6 (gate) + STR-7 (gel). La génération EST l'acte de clôture de
    la revue (cahier : « pack de revue de performance... document de revue
    à date, figé et horodaté ») — refusée tant qu'un écart au-delà du
    seuil n'a pas de commentaire de gestion sur sa ligne."""
    variance_rows = []
    if budget is not None:
        variance_rows = compute_variance(tenant, budget, user=user, threshold_pct=threshold_pct)
        if not can_close_review(variance_rows):
            raise ValidationError(
                _(
                    "Écart(s) au-delà du seuil sans commentaire de gestion : la revue ne "
                    "peut pas être clôturée."
                )
            )

    snapshot = {
        "objectives": _snapshot_objectives(tenant, user),
        "variance_lines": [serialize_variance_row(row) for row in variance_rows],
        "risks": _snapshot_risks(tenant),
    }

    pack = StgReviewPack(
        tenant=tenant,
        budget=budget,
        period_start=period_start,
        period_end=period_end,
        generated_at=timezone.now(),
        generated_by=user,
        snapshot=snapshot,
        created_by=user,
        updated_by=user,
    )
    pack.full_clean()
    pack.save()
    return pack
