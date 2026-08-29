"""Ecrans HTMX minimaux du module `strategy` (STR4) : arbre OKR (liste),
detail objectif avec check-ins, catalogue de benchmarks sectoriels. Meme
patron que `apps.crm.views` : chaque vue appelle directement les fonctions
de service, jamais l'API ninja."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.strategy.models import SECTOR_CHOICES, StgKeyResult, StgObjective
from apps.strategy.services.benchmarks import get_benchmarks_for_sector
from apps.strategy.services.objectives import add_key_result, create_objective, record_check_in
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
