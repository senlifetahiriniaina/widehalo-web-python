"""Ecrans HTMX minimaux de l'app `ai` (AI1, AI2). Meme patron deja etabli
dans tout ce depot : `@login_required` seul, le controle RBAC fin reste
porte par l'API (cf. docstring de `apps/ai/api.py`) — pour l'assistant
contextuel (AI2) cela signifie explicitement AUCUNE restriction de role au-
dela de l'authentification, cadrage identique a l'API."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.ai.models import AiAnomaly, AiInsight
from apps.ai.services.contextual_assistant import assist as run_contextual_assist
from apps.ai.services.natural_language_search import search as run_nl_search
from apps.ai.services.usage_budget import current_month_token_usage, get_or_create_usage_limit
from apps.core.context import get_current_tenant_id
from apps.core.models.tenant import Tenant
from apps.core.services.ai_context_registry import list_registered_contexts


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


@login_required
def assist_widget(request: HttpRequest) -> HttpResponse:
    """AI2 — page complete du widget « Assistant IA » : formulaire
    module/action (module presente sous forme de liste deroulante peuplee
    par le registre reel, cf. `list_registered_contexts()`) + zone de
    resultat HTMX (`assist_fragment` ci-dessous)."""
    return render(
        request,
        "ai/assist.html",
        {"modules": [ctx.module for ctx in list_registered_contexts()]},
    )


@login_required
def assist_fragment(request: HttpRequest) -> HttpResponse:
    """Fragment HTMX retourne par la soumission du formulaire de
    `assist_widget` — appelle le meme service que l'API (`apps.ai.services.
    contextual_assistant.assist`), jamais une logique dupliquee."""
    tenant = Tenant.objects.get(id=get_current_tenant_id())
    module = request.POST.get("module", "").strip()
    action = request.POST.get("action", "").strip() or "consulter"
    response = run_contextual_assist(
        module, action, tenant=tenant, user=request.user, locale=request.user.preferred_language
    )
    return render(request, "ai/_assist_result.html", {"result": response})


@login_required
def search_widget(request: HttpRequest) -> HttpResponse:
    """AI4 — page complete de l'ecran « Recherche en langage naturel » :
    champ de question libre + zone de resultat rendue directement (pas de
    fragment HTMX separe ici, `q` etant un parametre GET simple partageable
    par URL, comme l'ecran de recherche globale existant)."""
    query = request.GET.get("q", "").strip()
    result = None
    if query:
        tenant = Tenant.objects.get(id=get_current_tenant_id())
        result = run_nl_search(
            query, tenant=tenant, user=request.user, locale=request.user.preferred_language
        )
    return render(request, "ai/search.html", {"query": query, "result": result})


@login_required
def anomalies_list(request: HttpRequest) -> HttpResponse:
    """AI3 — liste simple des anomalies OUVERTES du tenant courant. Meme
    patron `@login_required` seul que le reste de cet ecran (cf. docstring
    de tete de fichier) : le controle RBAC fin (`ai.view_aianomaly`) reste
    porte par l'API, jamais duplique cote ecran HTMX."""
    anomalies = AiAnomaly.objects.filter(is_active=True, status=AiAnomaly.STATUS_OPEN)
    return render(request, "ai/anomalies_list.html", {"anomalies": anomalies})


@login_required
def insights_list(request: HttpRequest) -> HttpResponse:
    """AI5 — liste simple des insights proactifs du tenant courant. Meme
    patron `@login_required` seul que le reste de cet ecran (cf. docstring
    de tete de fichier) : posture RBAC deliberement OUVERTE (cf. docstring
    de `apps/ai/api.py`), jamais de restriction de role supplementaire
    cote ecran."""
    insights = AiInsight.objects.filter(is_active=True)
    return render(request, "ai/insights_list.html", {"insights": insights})
