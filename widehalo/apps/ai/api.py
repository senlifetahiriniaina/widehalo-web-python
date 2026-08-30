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
`@require_permission(...)` sur ces deux endpoints.

`POST /ai/search` (AI4, recherche en langage naturel) suit la MEME posture
RBAC ouverte que `POST /ai/assist` ci-dessus — meme raisonnement : elle ne
fait que router vers `apps.core.services.search.global_search`, deja
tenant-scope et deja filtre par permission RBAC PAR RESULTAT (chaque
document renvoye exige que l'utilisateur ait `view_<model>` sur son
content-type reel), donc aucune restriction de role supplementaire au
niveau de l'endpoint lui-meme n'apporterait de securite en plus — cf.
`apps.core.api_search.search` (`GET /search`, la recherche globale
existante) qui suit deja exactement cette meme posture ouverte.

`POST /ai/anomalies/detect` et `GET /ai/anomalies` (AI3, detection
d'anomalies cross-modules) reviennent en revanche a la posture RESTREINTE
de AI1 (`ai.view_aianomaly`/`ai.add_aianomaly`, memes roles admin/
direction que `AiUsageLimit`/`AiRequest`, cf. `ROLE_APP_PERMISSIONS["ai"]`)
— disclosed comme le choix pragmatique le plus simple compte tenu de la
granularite RBAC de ce depot (par APP, pas par modele, cf. docstring
`rbac_policy.py`) : une anomalie peut provenir d'`accounting`/`stocks`/
`projects`/`sales`, un decoupage fin par role-et-par-domaine-source
demanderait une granularite N2 par modele qui n'existe pas encore. Un
ecran filtre par role/domaine reste du perimetre futur, pas bloquant ici.
`add_aianomaly` n'est JAMAIS accorde a un utilisateur en pratique : les
`AiAnomaly` ne sont creees QUE par `services.anomaly_detection.
run_all_checks` (endpoint de detection, jamais une creation manuelle
directe d'anomalie exposee par ailleurs).

`POST /ai/insights/generate` et `GET /ai/insights` (AI5, insights
proactifs automatises) reviennent en revanche a la posture OUVERTE de
`assist`/`search` ci-dessus, PAS a la posture restreinte des anomalies —
choix disclosed qui merite d'etre explicite car il s'ecarte du precedent
le plus recent (anomalies) : `rbac_policy.py` (`ROLE_APP_PERMISSIONS["
admin"]["ai"]`, commentaire de tete de section) reserve explicitement et
nommement les « insights » (avec l'assistant contextuel et la recherche)
a une posture ouverte "sans permission de module dediee, meme posture que
`chat`" — contrairement aux anomalies (non nommees dans ce commentaire),
dont la posture restreinte est un choix pragmatique ulterieur et disclosed
de AI3. Un insight proactif reste par ailleurs une information de
pilotage utile a tout role en train de travailler sur son module
(commercial, production, RH), pas seulement `admin`/`direction` — cf.
`AiInsight.category` volontairement variee ("ventes"/"production"/"rh"/
"synthese").

`POST /ai/recommendations` (AI7, advisor d'actions/next-best-action) suit
la MEME posture OUVERTE — cf. commentaire de tete de `ROLE_APP_
PERMISSIONS["admin"]["ai"]` dans `rbac_policy.py` qui earmarque NOMMEMENT
"recommandations" (avec assistant/recherche/insights) pour cette posture
ouverte des AI1, exactement comme AI5 ci-dessus : aucune deviation a
disclosed ici, la decision etait deja actee au moment de AI1.

`POST /ai/data-query/ask` (GW4, passerelle IA locale d'analyse de donnees)
suit la MEME posture OUVERTE que `assist`/`search`/`insights`/
`recommendations` ci-dessus — AUCUN `@require_permission(...)` sur
l'endpoint lui-meme. Contrairement a ces quatre endpoints cependant, la
vraie restriction de securite n'est pas "aucune n'est necessaire" mais
DEPLACEE a l'interieur de `apps.ai.services.data_query_gateway.ask()` :
chaque tool du catalogue expose au LLM porte son propre `required_
permission` (`core.services.data_query_tool_registry`), verifie AVANT
meme que ce tool soit propose au LLM (cf. docstring de ce registre) — la
granularite de securite reelle est donc PAR TOOL, plus fine qu'un simple
`require_permission` global sur l'endpoint n'aurait pu l'exprimer (un
utilisateur authentifie quelconque peut poser une question, mais ne
recevra jamais de reponse s'appuyant sur un tool auquel il n'a pas droit)."""

from __future__ import annotations

from typing import Any

from ninja import Router, Schema

from apps.ai.models import AiAnomaly, AiDataQuery, AiInsight, AiRecommendation
from apps.ai.services.action_advisor import suggest as run_action_advisor
from apps.ai.services.anomaly_detection import run_all_checks
from apps.ai.services.automated_insights import generate as generate_insights
from apps.ai.services.contextual_assistant import assist as run_contextual_assist
from apps.ai.services.data_query_gateway import ask as run_data_query_ask
from apps.ai.services.natural_language_search import search as run_nl_search
from apps.ai.services.usage_budget import (
    current_month_token_usage,
    get_or_create_usage_limit,
)
from apps.core.models.tenant import Tenant
from apps.core.services.ai_context_registry import list_registered_contexts
from apps.core.services.permissions import require_permission, user_role_codes

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


class NlSearchIn(Schema):
    query: str


@router.post("/ai/search")
def nl_search_endpoint(request: Any, payload: NlSearchIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    user = request.auth
    locale = _resolve_locale(request)
    response = run_nl_search(payload.query, tenant=tenant, user=user, locale=locale)
    return dict(response)


def _serialize_anomaly(anomaly: AiAnomaly) -> dict[str, Any]:
    content_type = anomaly.content_type
    content_type_label = (
        f"{content_type.app_label}.{content_type.model}" if content_type is not None else None
    )
    return {
        "id": str(anomaly.id),
        "check_code": anomaly.check_code,
        "severity": anomaly.severity,
        "description": anomaly.description,
        "ai_narrative": anomaly.ai_narrative,
        "status": anomaly.status,
        "content_type_label": content_type_label,
        "object_id": anomaly.object_id,
        "created_at": anomaly.created_at.isoformat(),
    }


@router.post("/ai/anomalies/detect")
@require_permission("ai.add_aianomaly")
def detect_anomalies_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    created = run_all_checks(tenant)
    return {"results": [_serialize_anomaly(anomaly) for anomaly in created]}


@router.get("/ai/anomalies")
@require_permission("ai.view_aianomaly")
def list_anomalies_endpoint(request: Any) -> dict[str, Any]:
    # `AiAnomaly.objects` (TenantManager) est deja scope au tenant courant
    # — meme convention que `list_usage_requests_endpoint` ci-dessus.
    anomalies = AiAnomaly.objects.filter(is_active=True)
    status_filter = request.GET.get("status")
    if status_filter:
        anomalies = anomalies.filter(status=status_filter)
    severity_filter = request.GET.get("severity")
    if severity_filter:
        anomalies = anomalies.filter(severity=severity_filter)
    return {"results": [_serialize_anomaly(anomaly) for anomaly in anomalies[:200]]}


def _serialize_insight(insight: AiInsight) -> dict[str, Any]:
    return {
        "id": str(insight.id),
        "category": insight.category,
        "title": insight.title,
        "body": insight.body,
        "source_modules": insight.source_modules,
        "is_ai_generated": insight.is_ai_generated,
        "created_at": insight.created_at.isoformat(),
    }


@router.post("/ai/insights/generate")
def generate_insights_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    created = generate_insights(tenant)
    return {"results": [_serialize_insight(insight) for insight in created]}


@router.get("/ai/insights")
def list_insights_endpoint(request: Any) -> dict[str, Any]:
    # `AiInsight.objects` (TenantManager) est deja scope au tenant courant
    # — meme convention que `list_usage_requests_endpoint`/
    # `list_anomalies_endpoint` ci-dessus.
    insights = AiInsight.objects.filter(is_active=True)
    category_filter = request.GET.get("category")
    if category_filter:
        insights = insights.filter(category=category_filter)
    return {"results": [_serialize_insight(insight) for insight in insights[:200]]}


class RecommendationsIn(Schema):
    module: str
    action: str


def _primary_role_code(request: Any) -> str:
    # `suggest()` (cf. plan) prend un `role_code` UNIQUE, pas un ensemble —
    # contrairement a `_role_code()` de `contextual_assistant` (qui
    # concatene TOUS les roles, uniquement pour differencier une cle de
    # cache). Simplification disclosed : le premier role par ordre
    # alphabetique (deterministe) est retenu comme role "principal" du
    # contexte, "anon" a defaut de tout role — un utilisateur multi-role
    # reste couvert par au moins une regle si l'une de ses regles
    # correspond a N'IMPORTE LEQUEL de ses roles serait plus complet, mais
    # aucune regle enregistree en AI7 ne filtre encore par role (cf.
    # `apps.purchase.services.ai_advisor_registration`/`apps.mrp.services.
    # ai_advisor_registration`, toutes deux pertinentes "quel que soit le
    # role"), donc cette simplification n'a aucun effet observable a ce
    # stade — posee pour ne pas re-elargir la signature actee par le plan.
    user = getattr(request, "auth", None)
    if user is None:
        return "anon"
    codes = sorted(user_role_codes(user))
    return codes[0] if codes else "anon"


def _serialize_recommendation(recommendation: AiRecommendation) -> dict[str, Any]:
    return {
        "id": str(recommendation.id),
        "context_module": recommendation.context_module,
        "context_action": recommendation.context_action,
        "role_code": recommendation.role_code,
        "label": recommendation.label,
        "target_module": recommendation.target_module,
        "target_action_code": recommendation.target_action_code,
        "created_at": recommendation.created_at.isoformat(),
    }


@router.post("/ai/recommendations")
def suggest_recommendations_endpoint(request: Any, payload: RecommendationsIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    role_code = _primary_role_code(request)
    created = run_action_advisor(payload.module, payload.action, tenant=tenant, role_code=role_code)
    return {"results": [_serialize_recommendation(r) for r in created]}


@router.get("/ai/recommendations")
def list_recommendations_endpoint(request: Any) -> dict[str, Any]:
    # `AiRecommendation.objects` (TenantManager) est deja scope au tenant
    # courant — meme convention que `list_usage_requests_endpoint`/
    # `list_anomalies_endpoint`/`list_insights_endpoint` ci-dessus.
    recommendations = AiRecommendation.objects.filter(is_active=True)
    module_filter = request.GET.get("context_module")
    if module_filter:
        recommendations = recommendations.filter(context_module=module_filter)
    return {"results": [_serialize_recommendation(r) for r in recommendations[:200]]}


class DataQueryAskIn(Schema):
    question: str


def _serialize_data_query(record: AiDataQuery) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "question": record.question,
        "tools_called": record.tools_called,
        "answer": record.answer,
        "succeeded": record.succeeded,
        "provider_backend": record.provider_backend,
        "created_at": record.created_at.isoformat(),
    }


@router.post("/ai/data-query/ask")
def data_query_ask_endpoint(request: Any, payload: DataQueryAskIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    user = request.auth
    locale = _resolve_locale(request)
    record = run_data_query_ask(payload.question, tenant=tenant, user=user, locale=locale)
    return _serialize_data_query(record)
