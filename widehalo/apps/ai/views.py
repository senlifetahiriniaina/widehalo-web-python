"""Ecrans HTMX minimaux de l'app `ai` (AI1, AI2). Meme patron deja etabli
dans tout ce depot : `@login_required` seul, le controle RBAC fin reste
porte par l'API (cf. docstring de `apps/ai/api.py`) — pour l'assistant
contextuel (AI2) cela signifie explicitement AUCUNE restriction de role au-
dela de l'authentification, cadrage identique a l'API."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

from apps.ai.models import AiAnomaly, AiExternalProviderConsent, AiInsight
from apps.ai.services.action_advisor import suggest as run_action_advisor
from apps.ai.services.contextual_assistant import assist as run_contextual_assist
from apps.ai.services.data_query_gateway import ask as run_data_query_ask
from apps.ai.services.external_consent import (
    active_consent,
    grant_consent,
    outbound_data_disclosure,
    revoke_consent,
)
from apps.ai.services.natural_language_search import search as run_nl_search
from apps.ai.services.usage_budget import current_month_token_usage, get_or_create_usage_limit
from apps.core.context import get_current_tenant_id
from apps.core.models.tenant import Tenant
from apps.core.services.ai_assistant import StubAIProvider, get_ai_provider
from apps.core.services.ai_context_registry import list_registered_contexts
from apps.core.services.data_query_tool_registry import get_data_query_tool
from apps.core.services.permissions import user_role_codes

logger = logging.getLogger(__name__)


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
def ai_launcher(request: HttpRequest) -> HttpResponse:
    """Popup Assistant IA (FAB ambre, base.html) — meme construction de
    contexte que `assist_widget` (liste des modules enregistres via le
    registre reel), rendue en fragment (jamais `{% extends %}`). Le
    formulaire poste sur `ai:assist_fragment`, deja existant et inchange —
    aucun nouvel endpoint metier."""
    return render(
        request,
        "ai/_launcher.html",
        {"modules": [ctx.module for ctx in list_registered_contexts()]},
    )


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


@login_required
def recommendations_screen(request: HttpRequest) -> HttpResponse:
    """AI7 — formulaire module/action (module presente sous forme de liste
    deroulante peuplee par le registre reel `ai_context_registry`, meme
    convention que `assist_widget`) + resultat rendu directement (parametres
    GET simples partageables par URL, meme convention que `search_widget`).
    Meme patron `@login_required` seul (cf. docstring de tete de fichier) :
    posture RBAC deliberement OUVERTE (cf. docstring de `apps/ai/api.py`)."""
    module = request.GET.get("module", "").strip()
    action = request.GET.get("action", "").strip()
    recommendations = None
    if module and action:
        tenant = Tenant.objects.get(id=get_current_tenant_id())
        codes = sorted(user_role_codes(request.user))
        role_code = codes[0] if codes else "anon"
        recommendations = run_action_advisor(module, action, tenant=tenant, role_code=role_code)
    return render(
        request,
        "ai/recommendations.html",
        {
            "modules": [ctx.module for ctx in list_registered_contexts()],
            "module": module,
            "action": action,
            "recommendations": recommendations,
        },
    )


def _verification_url(tool: Any) -> str:
    """URL de l'ecran ou le chiffre d'un tool se recontrole, ou `""`.

    Jamais d'exception : un `verification_route` vide (aucun ecran ne
    recontrole ce chiffre) et une route devenue introuvable donnent le meme
    resultat — la source reste nommee, sans lien. Faire echouer le rendu de
    la reponse entiere parce qu'un lien de verification a bouge serait un
    remede pire que le mal."""
    route = getattr(tool, "verification_route", "") if tool is not None else ""
    if not route:
        return ""
    try:
        return reverse(route)
    except NoReverseMatch:
        logger.warning(
            "Route de verification %r introuvable pour le tool %r — source affichee sans lien.",
            route,
            getattr(tool, "code", "?"),
        )
        return ""


@login_required
def data_query_screen(request: HttpRequest) -> HttpResponse:
    """GW4 — ecran minimal « Questions-donnees IA » : champ question libre
    + reponse + liste des tools reellement utilises (parametre GET simple
    partageable par URL, meme convention que `search_widget`/
    `recommendations_screen` ci-dessus). Meme patron `@login_required` seul
    (cf. docstring de tete de fichier) : posture RBAC deliberement OUVERTE
    au niveau de l'ecran/l'API — la vraie restriction de securite est PAR
    TOOL, a l'interieur de `data_query_gateway.ask()` (cf. docstring de
    `apps/ai/api.py`)."""
    question = request.GET.get("question", "").strip()
    result = None
    tool_sources: list[dict[str, str]] = []
    if question:
        tenant = Tenant.objects.get(id=get_current_tenant_id())
        result = run_data_query_ask(
            question, tenant=tenant, user=request.user, locale=request.user.preferred_language
        )
        # "Sources consultées" (raffinement UI Sprint 11, L7) : `tools_called`
        # ne persiste que `code`/`args` (cf. `AiDataQuery.tools_called`) — on
        # enrichit ici, cote vue, avec le label/module lisible du registre
        # (`data_query_tool_registry`), sans toucher la boucle de tool-calling
        # elle-meme ni le format persiste en base.
        for tool_call in result.tools_called:
            tool = get_data_query_tool(tool_call.get("code", ""))
            tool_sources.append(
                {
                    "code": tool_call.get("code", ""),
                    "label": tool.label if tool else tool_call.get("code", ""),
                    "module": tool.module if tool else "",
                    # IA-8 (L7) : le lien de VERIFICATION. Le bloc « Sources
                    # consultees » existait deja, mais en `<strong>` : il
                    # nommait le rapport sans jamais y mener. Le critere
                    # demande « le lien vers l'ecran qui permet de verifier
                    # le chiffre » — nommer la source dit d'ou vient le
                    # chiffre, il ne permet pas de le recontroler.
                    #
                    # `reverse` est fait ICI et non dans le gabarit : une
                    # route retiree ou renommee doit degrader en lien
                    # absent, pas faire echouer le rendu de la reponse.
                    "verification_url": _verification_url(tool),
                }
            )
    return render(
        request,
        "ai/data_query.html",
        {"question": question, "result": result, "tool_sources": tool_sources},
    )


@login_required
def external_provider_consent(request: HttpRequest) -> HttpResponse:
    """IA-9 — l'ecran de consentement a l'envoi de donnees au dehors.

    **Ce qu'il ferme.** L'activation d'un fournisseur externe etait une
    variable d'environnement posee au redemarrage : aucun ecran, aucun
    formulaire, aucun modele, aucune entree d'audit, pas meme une ligne
    dans `.env.example`. Personne ne pouvait repondre a « depuis quand les
    donnees de cette societe sortent-elles, et qui l'a decide ? ».

    L'ecran affiche CE QUI SORT — deduit de ce que la passerelle transmet
    reellement, jamais une formule rassurante — AVANT de proposer
    d'accepter. Tant que le consentement n'est pas donne,
    `get_budget_gated_provider` retombe sur le stub : le bouton n'est pas
    une formalite, c'est lui qui ouvre le canal.

    Reserve au role `admin` : c'est une decision de gouvernance de la
    societe, pas un reglage d'utilisateur."""
    tenant = Tenant.objects.get(id=get_current_tenant_id())
    if "admin" not in user_role_codes(request.user):
        return HttpResponse(status=403)

    provider = get_ai_provider()
    backend = "stub" if isinstance(provider, StubAIProvider) else _configured_backend_label()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "grant" and backend != "stub":
            grant_consent(tenant, backend=backend, user=request.user)
        elif action == "revoke":
            revoke_consent(tenant, user=request.user)
        return redirect("ai:external_provider_consent")

    return render(
        request,
        "ai/external_provider_consent.html",
        {
            "backend": backend,
            "provider_is_configured": backend != "stub",
            "disclosure": outbound_data_disclosure(),
            "consent": active_consent(tenant),
            "history": AiExternalProviderConsent.objects.filter(tenant=tenant)[:20],
        },
    )


def _configured_backend_label() -> str:
    from django.conf import settings

    config: dict[str, str] = getattr(settings, "AI_PROVIDER_CONFIG", {}) or {}
    return config.get("backend", "custom")


@login_required
def index(request: HttpRequest) -> HttpResponse:
    """T10 — la porte d'entree du module, qui n'existait pas.

    **Le defaut ferme.** Les sept ecrans de ce module etaient routes,
    testes, fonctionnels — et cites par RIEN. `ai` n'appartenait a aucun
    groupe de `_MENU_GROUPS`, et `apps/ai/urls.py` n'avait meme pas de route
    racine : `/ai/` rendait 404. Seul le bouton flottant d'assistance etait
    cable, vers un fragment. C'est le meme defaut que `flows` avant T8, mais
    sur un module entier.

    **Pourquoi une porte plutot que sept entrees de menu.** Sept lignes dans
    la barre laterale pour un module que la plupart des roles n'ouvriront
    qu'occasionnellement noierait les modules metier. Une entree, un ecran
    qui presente les sept, et qui DIT dans quel etat ils sont.

    **Cet ecran ne se contente pas de lister : il compte.** Un accueil dont
    toutes les valeurs sont ecrites en dur est un ecran mort — il affiche la
    meme chose le premier jour et le millieme. Les anomalies ouvertes et les
    insights sont donc lus reellement, et l'etat du fournisseur IA est celui
    qui est reellement configure : sans connecteur, le module rend des
    reponses de repli (§12.3) et l'exploitant doit l'apprendre ici plutot
    que de s'en apercevoir sur une reponse decevante.

    **Le budget est le seul ecran restreint**, et la restriction n'est pas
    de moi : `rbac_policy` reserve la permission de module `ai` a
    `admin`/`direction` en ecrivant que les fonctions IA a usage large sont
    volontairement ouvertes a tout utilisateur authentifie. La tuile de
    budget suit donc la permission ; les six autres, non."""
    provider = get_ai_provider()
    return render(
        request,
        "ai/index.html",
        {
            "anomalies_ouvertes": AiAnomaly.objects.filter(
                is_active=True, status=AiAnomaly.STATUS_OPEN
            ).count(),
            "insights_actifs": AiInsight.objects.filter(is_active=True).count(),
            "modules_assistes": len(list_registered_contexts()),
            "connecteur_absent": isinstance(provider, StubAIProvider),
            "connecteur_label": _configured_backend_label(),
            "peut_voir_le_budget": bool(user_role_codes(request.user) & {"admin", "direction"}),
        },
    )
