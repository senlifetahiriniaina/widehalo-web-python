"""Écrans HTMX/session-authentifiés du module `simulation` (§13.6) —
`@login_required`, appel direct aux `services/*` de `simulation`, jamais
l'API JWT interne (`apps.simulation.api`) — même patron que `apps.pos.
views` (cf. sa docstring de tête).

**Trois gabarits** (budget écrans) : `simulation/index.html` (bibliothèque
de scénarios), `simulation/workbench.html` (atelier de scénarios — leviers,
indicateurs, point mort/sensibilité, projection de trésorerie à 13
semaines, TOUS calculés côté client en < 100 ms via `static/js/
simulation_engine.js`, cf. cahier §11.1 « deux exceptions assumées à la
règle du rendu serveur » : la caisse POS et l'atelier de simulation),
`simulation/compare.html` (comparateur, SIM-6)."""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.views.tenant_web import resolve_tenant
from apps.simulation.levers import catalog_as_dicts
from apps.simulation.models import SimBaseline, SimScenario
from apps.simulation.services.baseline import deserialize_baseline_data, refresh_baseline
from apps.simulation.services.engine import rank_levers_by_sensitivity
from apps.simulation.services.scenarios import (
    archive_scenario,
    compare_scenarios,
    create_scenario,
    list_scenarios,
    update_scenario,
)
from apps.simulation.services.scoping import assert_can_view_scenario


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _latest_baseline(tenant):  # type: ignore[no-untyped-def]
    return SimBaseline.objects.filter(tenant=tenant).order_by("-extracted_at").first()


# ---------------------------------------------------------------------------
# Bibliothèque de scénarios
# ---------------------------------------------------------------------------


@login_required
def library(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("simulation.view_simscenario"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    scenarios = list_scenarios(tenant, request.user)
    baseline = _latest_baseline(tenant)
    return render(
        request,
        "simulation/index.html",
        {
            "scenarios": scenarios,
            "baseline": baseline,
            "can_refresh": request.user.has_perm("simulation.add_simbaseline"),
            "can_create": request.user.has_perm("simulation.add_simscenario"),
            "error": request.GET.get("error", ""),
        },
    )


@login_required
def baseline_refresh(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("simulation.add_simbaseline"):
        return HttpResponse(status=403)
    try:
        refresh_baseline(resolve_tenant(request), user=request.user)
    except ValidationError as exc:
        return redirect(f"/simulation/?error={quote(_error_message(exc))}")
    return redirect("simulation:index")


@login_required
def archive(request: HttpRequest, scenario_id: str) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=403)
    scenario = get_object_or_404(SimScenario, id=scenario_id)
    try:
        archive_scenario(scenario, user=request.user)
    except PermissionDenied:
        return HttpResponse(status=403)
    return redirect("simulation:index")


# ---------------------------------------------------------------------------
# Atelier de scénarios (SIM-1, SIM-3, SIM-4, SIM-7, point mort/sensibilité)
# ---------------------------------------------------------------------------


@login_required
def workbench(request: HttpRequest, scenario_id: str | None = None) -> HttpResponse:
    """GET : rend l'atelier — socle + catalogue de leviers + (scénario
    existant, le cas échéant) EMBARQUÉS via `json_script` (même discipline
    que `apps.pos.views.sale_screen`) pour que `static/js/simulation_
    engine.js` recalcule tous les indicateurs localement, sans aucun
    aller-retour serveur (SIM-1). POST : crée ou met à jour le scénario —
    le serveur recalcule et VALIDE le calcul client par tolérance (SIM-4,
    `services.scenarios._assert_client_matches_server`), il ne lui fait
    jamais confiance tel quel."""
    if not request.user.has_perm("simulation.view_simscenario"):
        return HttpResponse(status=403)

    tenant = resolve_tenant(request)
    scenario = None
    if scenario_id:
        scenario = get_object_or_404(
            SimScenario.objects.select_related("baseline", "owner"), id=scenario_id
        )
        try:
            assert_can_view_scenario(scenario, request.user)
        except PermissionDenied:
            return HttpResponse(status=403)

    if request.method == "POST":
        required_perm = "simulation.change_simscenario" if scenario else "simulation.add_simscenario"
        if not request.user.has_perm(required_perm):
            return HttpResponse(status=403)
        try:
            payload = json.loads(request.POST.get("scenario_json") or "{}", parse_float=Decimal)
            levers = payload.get("levers", {})
            client_indicators = payload.get("client_computed_indicators")
            if scenario is None:
                baseline = get_object_or_404(SimBaseline, id=request.POST.get("baseline_id"))
                scenario = create_scenario(
                    tenant,
                    baseline=baseline,
                    name=payload.get("name") or "Scénario",
                    description=payload.get("description", ""),
                    is_shared=bool(payload.get("is_shared", False)),
                    levers=levers,
                    owner=request.user,
                    client_computed_indicators=client_indicators,
                    user=request.user,
                )
            else:
                scenario = update_scenario(
                    scenario,
                    levers=levers,
                    user=request.user,
                    name=payload.get("name"),
                    description=payload.get("description"),
                    is_shared=payload.get("is_shared"),
                    client_computed_indicators=client_indicators,
                )
        except (ValidationError, PermissionDenied, KeyError, ValueError, TypeError) as exc:
            detail = _error_message(exc) if isinstance(exc, ValidationError | PermissionDenied) else str(exc)
            return redirect(f"{request.path}?error={quote(detail)}")
        return redirect("simulation:workbench", scenario_id=scenario.id)

    baseline = scenario.baseline if scenario else _latest_baseline(tenant)
    scenario_data = (
        {
            "name": scenario.name,
            "description": scenario.description,
            "is_shared": scenario.is_shared,
            "levers": scenario.levers,
        }
        if scenario
        else None
    )
    return render(
        request,
        "simulation/workbench.html",
        {
            "scenario": scenario,
            "baseline": baseline,
            "baseline_data": baseline.data if baseline else None,
            "scenario_data": scenario_data,
            "lever_catalog": catalog_as_dicts(),
            "error": request.GET.get("error", ""),
        },
    )


@login_required
def sensitivity_data(request: HttpRequest, scenario_id: str) -> JsonResponse:
    """Point mort et sensibilité — appel AJAX depuis l'atelier (onglet
    dédié) : classement des leviers par poids réel sur le résultat
    (cahier §13.6). Renvoyé en JSON, jamais recalculable côté client seul
    (nécessite plusieurs appels au moteur, cf. `services.engine.rank_
    levers_by_sensitivity`) — coût jugé acceptable en dehors du chemin
    « chaque mouvement de curseur » couvert par SIM-1."""
    scenario = get_object_or_404(SimScenario.objects.select_related("baseline"), id=scenario_id)
    try:
        assert_can_view_scenario(scenario, request.user)
    except PermissionDenied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    baseline_data = deserialize_baseline_data(scenario.baseline)
    levers = {code: Decimal(str(value)) for code, value in scenario.levers.items()}
    rankings = rank_levers_by_sensitivity(baseline_data, levers)
    return JsonResponse(
        {
            "results": [
                {**row, "delta_resultat_mga": float(row["delta_resultat_mga"])} for row in rankings
            ]
        }
    )


# ---------------------------------------------------------------------------
# Comparateur (SIM-6)
# ---------------------------------------------------------------------------


@login_required
def compare(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("simulation.view_simscenario"):
        return HttpResponse(status=403)
    # `getlist` (pas `get`) : la bibliothèque (`simulation/index.html`)
    # soumet une case à cocher par scénario, donc plusieurs paramètres
    # `ids=` distincts dans la query string, jamais une seule valeur
    # jointe par virgules.
    ids = [value for value in request.GET.getlist("ids") if value]
    rows: list[dict] = []  # type: ignore[type-arg]
    error = ""
    if ids:
        try:
            rows = compare_scenarios(request.user, ids)
        except ValidationError as exc:
            error = _error_message(exc)
    all_scenarios = list_scenarios(resolve_tenant(request), request.user)
    return render(
        request,
        "simulation/compare.html",
        {"rows": rows, "error": error, "selected_ids": ids, "all_scenarios": all_scenarios},
    )
