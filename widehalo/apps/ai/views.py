"""Ecrans HTMX minimaux de l'app `ai` (AI1). Meme patron deja etabli dans
tout ce depot : `@login_required` seul, le controle RBAC fin reste porte
par l'API (cf. docstring de `apps/ai/api.py`)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.ai.services.usage_budget import current_month_token_usage, get_or_create_usage_limit
from apps.core.context import get_current_tenant_id
from apps.core.models.tenant import Tenant


@login_required
def usage_budget(request: HttpRequest) -> HttpResponse:
    tenant = Tenant.objects.get(id=get_current_tenant_id())
    usage_limit = get_or_create_usage_limit(tenant)
    used = current_month_token_usage(tenant)
    return render(
        request,
        "ai/usage_budget.html",
        {
            "usage_limit": usage_limit,
            "current_month_usage": used,
            "usage_pct": (
                round(used * 100 / usage_limit.monthly_token_budget)
                if usage_limit.monthly_token_budget
                else 0
            ),
        },
    )
