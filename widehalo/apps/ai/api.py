"""API django-ninja du module `ai` (AI1, budget de tokens). Reservee a
`admin`/`direction` (cf. `apps.core.services.rbac_policy.
ROLE_APP_PERMISSIONS["ai"]`) — l'administration du cout/budget IA d'un
tenant est une operation de pilotage transverse, pas une action courante
de tous les roles. Les futures fonctionnalites accessibles a tous les
roles (assistant contextuel, recherche, insights, recommandations, cf.
AI2-AI7) suivront une posture RBAC plus ouverte, disclosed a chaque
etape correspondante."""

from __future__ import annotations

from typing import Any

from ninja import Router, Schema

from apps.ai.services.usage_budget import (
    current_month_token_usage,
    get_or_create_usage_limit,
)
from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission

router = Router(tags=["ai"])


class UsageLimitIn(Schema):
    monthly_token_budget: int
    alert_threshold_pct: int = 80
    hard_stop: bool = True


def _serialize_usage_limit(tenant: Tenant) -> dict[str, Any]:
    usage_limit = get_or_create_usage_limit(tenant)
    used = current_month_token_usage(tenant)
    return {
        "monthly_token_budget": usage_limit.monthly_token_budget,
        "alert_threshold_pct": usage_limit.alert_threshold_pct,
        "hard_stop": usage_limit.hard_stop,
        "current_month_usage": used,
        "over_alert_threshold": (
            usage_limit.monthly_token_budget > 0
            and used * 100 / usage_limit.monthly_token_budget >= usage_limit.alert_threshold_pct
        ),
    }


@router.get("/ai/usage/budget")
@require_permission("ai.view_aiusagelimit")
def get_usage_budget_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    return _serialize_usage_limit(tenant)


@router.post("/ai/usage/budget")
@require_permission("ai.change_aiusagelimit")
def update_usage_budget_endpoint(request: Any, payload: UsageLimitIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    usage_limit = get_or_create_usage_limit(tenant)
    usage_limit.monthly_token_budget = payload.monthly_token_budget
    usage_limit.alert_threshold_pct = payload.alert_threshold_pct
    usage_limit.hard_stop = payload.hard_stop
    usage_limit.save(update_fields=["monthly_token_budget", "alert_threshold_pct", "hard_stop"])
    return _serialize_usage_limit(tenant)


@router.get("/ai/usage")
@require_permission("ai.view_airequest")
def list_usage_requests_endpoint(request: Any) -> dict[str, Any]:
    # Pas de resolution explicite du tenant ici : `AiRequest.objects`
    # (TenantManager) est deja scope au tenant courant (deny-by-default),
    # contrairement aux endpoints d'ecriture ci-dessus qui doivent passer
    # un `Tenant` explicite aux fonctions de service.
    from apps.ai.models import AiRequest

    requests_qs = AiRequest.objects.filter(is_active=True)[:200]
    return {
        "results": [
            {
                "id": str(r.id),
                "feature": r.feature,
                "prompt_tokens_estimate": r.prompt_tokens_estimate,
                "completion_tokens_estimate": r.completion_tokens_estimate,
                "provider_backend": r.provider_backend,
                "succeeded": r.succeeded,
                "created_at": r.created_at.isoformat(),
            }
            for r in requests_qs
        ]
    }
