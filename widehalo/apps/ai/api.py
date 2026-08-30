"""API django-ninja du module `ai`. Les endpoints de budget (AI1) restent
reserves a `admin`/`direction` (cf. `apps.core.services.rbac_policy.
ROLE_APP_PERMISSIONS["ai"]`) — l'administration du cout/budget IA d'un
tenant est une operation de pilotage transverse, pas une action courante
de tous les roles.

`POST /ai/assist` et `GET /ai/assist/modules` (AI2, assistant contextuel
par page/action) suivent au contraire une posture RBAC deliberement
OUVERTE — cadrage explicite du plan : la guidance contextuelle est utile a
TOUT role en train de travailler, meme discipline que `chat`
(`apps.core.services.rbac_policy` exclut deliberement `chat` de sa
matrice de permissions). Seule l'authentification JWT par defaut
(`config/api.py::NinjaAPI(auth=JWTAuth())`) s'applique, AUCUN
`@require_permission(...)` sur ces deux endpoints."""

from __future__ import annotations

from typing import Any

from ninja import Router, Schema

from apps.ai.services.contextual_assistant import assist as run_contextual_assist
from apps.ai.services.usage_budget import (
    current_month_token_usage,
    get_or_create_usage_limit,
)
from apps.core.models.tenant import Tenant
from apps.core.services.ai_context_registry import list_registered_contexts
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


class AssistIn(Schema):
    module: str
    action: str


def _resolve_locale(request: Any) -> str:
    # `Accept-Language` explicite prioritaire (cf. `tests/i18n/
    # test_accept_language.py`, meme convention deja etablie ailleurs dans
    # ce depot) ; a defaut, la langue preferee de l'utilisateur authentifie
    # (`User.preferred_language`, cf. `apps.reporting.views.generate_submit`
    # qui l'utilise deja de la meme facon) ; "fr" en tout dernier recours.
    header = request.headers.get("Accept-Language")
    if header:
        return header.split(",")[0].strip()
    user = getattr(request, "auth", None)
    preferred = getattr(user, "preferred_language", None)
    return preferred or "fr"


@router.post("/ai/assist")
def assist_endpoint(request: Any, payload: AssistIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    user = request.auth
    locale = _resolve_locale(request)
    response = run_contextual_assist(
        payload.module, payload.action, tenant=tenant, user=user, locale=locale
    )
    return dict(response)


@router.get("/ai/assist/modules")
def list_assist_modules_endpoint(request: Any) -> dict[str, Any]:
    del request  # non utilise : liste globale, pas de scoping tenant/role
    return {
        "results": [
            {
                "module": ctx.module,
                "has_context_builder": ctx.context_builder is not None,
            }
            for ctx in list_registered_contexts()
        ]
    }
