"""Ecrans HTMX minimaux du module `strategy` (STR4) : arbre OKR (liste),
detail objectif avec check-ins, catalogue de benchmarks sectoriels. Meme
patron que `apps.crm.views` : chaque vue appelle directement les fonctions
de service, jamais l'API ninja."""

from __future__ import annotations

import contextlib
import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.strategy.models import (
    SECTOR_CHOICES,
    StgBudget,
    StgInitiative,
    StgKeyResult,
    StgObjective,
    StgReviewPack,
    StgRisk,
)
from apps.strategy.services.benchmarks import get_benchmarks_for_sector
from apps.strategy.services.budget import (
    add_variance_comment,
    compute_variance,
    create_budget,
    create_budget_from_forecast_publication,
    create_budget_from_simulation_scenario,
    lock_budget,
    revise_budget,
)
from apps.strategy.services.capacity_review import (
    DEFAULT_HORIZON_DAYS,
    DEFAULT_OVERLOAD_THRESHOLD_PCT,
    build_capacity_outlook,
)
from apps.strategy.services.objectives import (
    activate_objective,
    add_key_result,
    create_objective,
    record_check_in,
)
from apps.strategy.services.review_pack import generate_review_pack
from apps.strategy.services.risks import create_risk, reassess_risk
from apps.strategy.services.scoping import assert_can_manage_level, scope_objectives_for_user

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="title", label="Titre"),
    Column(key="level", label="Niveau"),
    Column(key="status", label="Statut", searchable=False),
]


@login_required
def objective_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    queryset = scope_objectives_for_user(StgObjective.objects.filter(is_active=True), user, tenant)
    return smart_table_response(
        request,
        table_key="strategy.objectives",
        columns=COLUMNS,
        queryset=queryset,
        page_template="strategy/list.html",
        page_context={"row_url_name": "strategy:detail"},
    )


@login_required
def objective_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None
    if request.method == "POST":
        level = request.POST.get("level", StgObjective.LEVEL_INDIVIDUAL)
        department_id = request.POST.get("department_id") or None
        try:
            assert_can_manage_level(user, level=level, department_id=department_id, tenant=tenant)
            objective = create_objective(
                tenant,
                title=request.POST.get("title", ""),
                level=level,
                description=request.POST.get("description", ""),
                owner=user,
                department_id=department_id,
                period_start=request.POST.get("period_start"),
                period_end=request.POST.get("period_end"),
                created_by=user,
            )
            from django.shortcuts import redirect

            return redirect("strategy:detail", objective_id=objective.id)
        except (ValidationError, PermissionDenied) as exc:
            error = str(exc)
    return render(
        request,
        "strategy/create.html",
        {"error": error, "levels": StgObjective.LEVEL_CHOICES},
    )


@login_required
def objective_detail(request: HttpRequest, objective_id: str) -> HttpResponse:
    objective = get_object_or_404(StgObjective, id=objective_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_key_result":
                add_key_result(
                    objective,
                    metric_name=request.POST.get("metric_name", ""),
                    target_value=Decimal(request.POST.get("target_value", "0")),
                    unit=request.POST.get("unit", ""),
                )
            elif action == "add_check_in":
                key_result = get_object_or_404(StgKeyResult, id=request.POST.get("key_result_id"))
                record_check_in(
                    key_result,
                    date=dt.date.fromisoformat(request.POST.get("date", "")),
                    value=Decimal(request.POST.get("value", "0")),
                    comment=request.POST.get("comment", ""),
                    author=cast(User, request.user),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)
        objective.refresh_from_db()

    key_results = objective.key_results.filter(is_active=True)
    return render(
        request,
        "strategy/detail.html",
        {
            "objective": objective,
            "key_results": key_results,
            "error": error,
        },
    )


@login_required
def benchmark_catalog(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    sector_code = request.GET.get("sector", SECTOR_CHOICES[0][0])
    benchmarks = get_benchmarks_for_sector(tenant, sector_code)
    return render(
        request,
        "strategy/benchmarks.html",
        {"benchmarks": benchmarks, "sectors": SECTOR_CHOICES, "current_sector": sector_code},
    )


@login_required
def capacity_outlook(request: HttpRequest) -> HttpResponse:
    """CAP1-2 (cf. plan) : tableau capacite-vs-charge sur 90 jours. C'est
    le point d'entree "vivant" (consulte par les decideurs) qui declenche
    la notification `direction`/`resp_production` en cas de surcharge
    (`notify=True`, le defaut de `build_capacity_outlook`) — a la
    difference du rapport `CAP-90J` du catalogue `reporting`
    (`notify=False` la, cf. sa docstring : un export/planification
    periodique ne doit pas re-notifier a chaque generation). **Limite
    disclosed** : chaque consultation de cet ecran renvoie donc une
    notification si le seuil reste depasse (pas de deduplication "deja
    notifie pour cette semaine cette semaine-ci") — acceptable pour un
    ecran de pilotage consulte occasionnellement par la direction, a
    affiner avec une fenetre anti-spam si l'usage reel montre une
    consultation trop frequente. RBAC deja couverte par la permission
    d'app `strategy` (view) existante, aucune permission dediee
    necessaire."""
    tenant = resolve_tenant(request)
    try:
        horizon_days = int(request.GET.get("horizon_days", DEFAULT_HORIZON_DAYS))
    except ValueError:
        horizon_days = DEFAULT_HORIZON_DAYS
    outlook = build_capacity_outlook(tenant, horizon_days=horizon_days)
    return render(
        request,
        "strategy/capacity_outlook.html",
        {
            "outlook": outlook,
            "horizon_days": horizon_days,
            "overload_threshold_pct": DEFAULT_OVERLOAD_THRESHOLD_PCT,
        },
    )


# ---------------------------------------------------------------------------
# Pilotage (cahier §13.3, STR-3..STR-8) — budget, initiatives, revue, risques
# ---------------------------------------------------------------------------


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def pilotage(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("strategy.view_stgbudget"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    tab = request.GET.get("tab", "budget")
    can_manage = request.user.has_perm("strategy.add_stgbudget")
    context = {"tab": tab, "can_manage": can_manage, "error": request.GET.get("error", "")}

    if tab == "initiatives":
        context["initiatives"] = StgInitiative.objects.filter(tenant=tenant).select_related(
            "objective"
        )
    elif tab == "revue":
        context["budgets"] = StgBudget.objects.filter(tenant=tenant)
        context["packs"] = StgReviewPack.objects.filter(tenant=tenant).order_by("-generated_at")
        budget_id = request.GET.get("budget_id")
        if budget_id:
            budget = StgBudget.objects.filter(tenant=tenant, id=budget_id).first()
            if budget is not None:
                context["selected_budget"] = budget
                context["variance_rows"] = compute_variance(tenant, budget, user=request.user)
    elif tab == "risques":
        context["risks"] = StgRisk.objects.filter(tenant=tenant).order_by("-probability", "-impact")
    elif tab == "tableau_direction":
        context["at_risk_objectives"] = StgObjective.objects.filter(
            tenant=tenant, status=StgObjective.STATUS_AT_RISK, is_active=True
        )[:2]
        context["top_risks"] = StgRisk.objects.filter(tenant=tenant).order_by(
            "-probability", "-impact"
        )[:2]
        latest_budget = (
            StgBudget.objects.filter(tenant=tenant, is_locked=True).order_by("-version").first()
        )
        context["latest_budget"] = latest_budget
        if latest_budget is not None:
            variances = compute_variance(tenant, latest_budget, user=request.user)
            context["significant_variances"] = [v for v in variances if v["exceeds_threshold"]][:2]
        from apps.forecast.services.public import get_latest_published_forecast

        context["latest_forecast"] = get_latest_published_forecast(tenant)
    else:
        context["budgets"] = StgBudget.objects.filter(tenant=tenant)
    return render(request, "strategy/pilotage.html", context)


@login_required
def budget_create(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.add_stgbudget"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    source = request.POST.get("source", StgBudget.SOURCE_MANUAL)
    name = request.POST.get("name", "").strip()
    try:
        if source == StgBudget.SOURCE_SIMULATION:
            create_budget_from_simulation_scenario(
                tenant,
                scenario_id=request.POST.get("scenario_id", ""),
                name=name,
                period_start=request.POST.get("period_start"),
                period_end=request.POST.get("period_end"),
                created_by=request.user,
            )
        elif source == StgBudget.SOURCE_FORECAST:
            create_budget_from_forecast_publication(tenant, name=name, created_by=request.user)
        else:
            create_budget(
                tenant,
                name=name,
                period_start=request.POST.get("period_start"),
                period_end=request.POST.get("period_end"),
                lines=[],
                created_by=request.user,
            )
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(f"/strategy/pilotage/?tab=budget&error={quote(_error_message(exc))}")
    return redirect("/strategy/pilotage/?tab=budget")


@login_required
def budget_lock(request: HttpRequest, budget_id: str) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.change_stgbudget"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    budget = get_object_or_404(StgBudget, tenant=tenant, id=budget_id)
    with contextlib.suppress(ValidationError):
        lock_budget(budget, user=request.user)
    return redirect("/strategy/pilotage/?tab=budget")


@login_required
def budget_revise(request: HttpRequest, budget_id: str) -> HttpResponse:
    """STR-3 : « une révision crée une version horodatée, l'ancienne reste
    consultable et comparable. » Écran minimal (cohérent avec `budget_
    create`, qui n'expose pas non plus d'éditeur de `lines` détaillé) :
    reprend TELLES QUELLES les lignes de la version précédente — l'ajustement
    des montants se fait aujourd'hui via l'API (`revise_budget` accepte des
    `lines` explicites), jamais un éditeur de grille sur cet écran."""
    if request.method != "POST" or not request.user.has_perm("strategy.add_stgbudget"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    budget = get_object_or_404(StgBudget, tenant=tenant, id=budget_id)
    try:
        revise_budget(budget, lines=budget.lines, created_by=request.user)
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(f"/strategy/pilotage/?tab=budget&error={quote(_error_message(exc))}")
    return redirect("/strategy/pilotage/?tab=budget")


@login_required
def budget_variance_comment(request: HttpRequest, budget_id: str) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.change_stgbudget"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    budget = get_object_or_404(StgBudget, tenant=tenant, id=budget_id)
    try:
        add_variance_comment(
            budget,
            line_key_value=request.POST.get("line_key", ""),
            text=request.POST.get("text", ""),
            user=request.user,
        )
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(
            f"/strategy/pilotage/?tab=revue&budget_id={budget_id}&error={quote(_error_message(exc))}"
        )
    return redirect(f"/strategy/pilotage/?tab=revue&budget_id={budget_id}")


@login_required
def initiative_create(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.add_stginitiative"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    objective = get_object_or_404(StgObjective, tenant=tenant, id=request.POST.get("objective_id"))
    initiative = StgInitiative(
        tenant=tenant,
        objective=objective,
        title=request.POST.get("title", ""),
        description=request.POST.get("description", ""),
        due_date=request.POST.get("due_date") or None,
        created_by=request.user,
        updated_by=request.user,
    )
    with contextlib.suppress(ValidationError):
        initiative.full_clean()
        initiative.save()
        from apps.chat.services.public import get_or_create_document_channel

        get_or_create_document_channel(
            tenant=tenant,
            content_object=initiative,
            participants=[request.user],
            title=initiative.title,
        )
    return redirect("/strategy/pilotage/?tab=initiatives")


@login_required
def review_pack_generate(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.add_stgreviewpack"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    budget_id = request.POST.get("budget_id")
    budget = StgBudget.objects.filter(tenant=tenant, id=budget_id).first() if budget_id else None
    try:
        generate_review_pack(
            tenant,
            budget=budget,
            period_start=request.POST.get("period_start"),
            period_end=request.POST.get("period_end"),
            user=request.user,
        )
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(f"/strategy/pilotage/?tab=revue&error={quote(_error_message(exc))}")
    return redirect("/strategy/pilotage/?tab=revue")


@login_required
def review_pack_detail(request: HttpRequest, pack_id: str) -> HttpResponse:
    if not request.user.has_perm("strategy.view_stgreviewpack"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    pack = get_object_or_404(StgReviewPack, tenant=tenant, id=pack_id)
    return render(request, "strategy/review_pack_detail.html", {"pack": pack})


@login_required
def risk_create(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.add_stgrisk"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    with contextlib.suppress(ValidationError, ValueError):
        create_risk(
            tenant,
            title=request.POST.get("title", ""),
            probability=int(request.POST.get("probability", 1)),
            impact=int(request.POST.get("impact", 1)),
            description=request.POST.get("description", ""),
            control_measure=request.POST.get("control_measure", ""),
            owner=request.user,
            created_by=request.user,
        )
    return redirect("/strategy/pilotage/?tab=risques")


@login_required
def risk_reassess(request: HttpRequest, risk_id: str) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("strategy.change_stgrisk"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    risk = get_object_or_404(StgRisk, tenant=tenant, id=risk_id)
    with contextlib.suppress(ValidationError, ValueError):
        reassess_risk(
            risk,
            probability=int(request.POST.get("probability", risk.probability)),
            impact=int(request.POST.get("impact", risk.impact)),
            control_measure=request.POST.get("control_measure", risk.control_measure),
            user=request.user,
        )
    return redirect("/strategy/pilotage/?tab=risques")


@login_required
def objective_activate(request: HttpRequest, objective_id: str) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    objective = get_object_or_404(StgObjective, tenant=tenant, id=objective_id)
    try:
        assert_can_manage_level(
            request.user,
            level=objective.level,
            department_id=objective.department_id,
            tenant=tenant,
        )
    except PermissionDenied:
        return HttpResponse(status=403)
    try:
        activate_objective(objective)
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(f"/strategy/{objective_id}/?error={quote(_error_message(exc))}")
    return redirect("strategy:detail", objective_id=objective.id)
