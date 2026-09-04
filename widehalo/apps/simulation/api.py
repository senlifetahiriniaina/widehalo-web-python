"""API django-ninja du module `simulation` (§13.6) — authentifiée par
jeton JWT (`config.api.api`), même discipline que `apps.pos.api` (cf. sa
docstring de tête) : surface programmatique complète, PAS la surface
réellement consommée par l'atelier de scénarios web (`templates/
simulation/workbench.html`), qui utilise ses propres vues session-
authentifiées (`apps.simulation.views`) appelant les MÊMES fonctions de
`apps.simulation.services.*`."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router

from apps.core.services.permissions import require_permission
from apps.simulation.levers import catalog_as_dicts
from apps.simulation.models import SimBaseline, SimScenario
from apps.simulation.schemas import (
    AiProposeIn,
    BaselineOut,
    CompareIn,
    LeverDefinitionOut,
    ScenarioComparisonRowOut,
    ScenarioCreateIn,
    ScenarioOut,
    ScenarioUpdateIn,
    SensitivityRowOut,
)
from apps.simulation.services.baseline import deserialize_baseline_data, refresh_baseline
from apps.simulation.services.engine import rank_levers_by_sensitivity
from apps.simulation.services.scenarios import (
    apply_ai_proposed_levers,
    archive_scenario,
    compare_scenarios,
    create_scenario,
    list_scenarios,
    update_scenario,
)
from apps.simulation.services.scoping import assert_can_view_scenario

router = Router(tags=["simulation"])


def _tenant(request):  # type: ignore[no-untyped-def]
    from apps.core.models.tenant import Tenant

    return Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))


def _serialize_baseline(baseline: SimBaseline) -> BaselineOut:
    return BaselineOut(
        id=str(baseline.id),
        extracted_at=baseline.extracted_at,
        period_start=baseline.period_start,
        period_end=baseline.period_end,
        as_of_date=baseline.as_of_date,
        regulatory_param_version=baseline.regulatory_param_version,
        open_items_total_count=baseline.open_items_total_count,
        open_items_included_count=baseline.open_items_included_count,
        degraded=bool(baseline.data.get("degraded", False)),
    )


def _serialize_scenario(scenario: SimScenario) -> ScenarioOut:
    return ScenarioOut(
        id=str(scenario.id),
        baseline_id=str(scenario.baseline_id),
        name=scenario.name,
        description=scenario.description,
        owner_id=str(scenario.owner_id),
        owner_email=scenario.owner.email if scenario.owner_id else "",
        is_shared=scenario.is_shared,
        ai_generated=scenario.ai_generated,
        ai_request_text=scenario.ai_request_text,
        levers=scenario.levers,
        indicators=scenario.computed_indicators,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
    )


@router.get("/simulation/levers", response=list[LeverDefinitionOut])
@require_permission("simulation.view_simscenario")
def list_levers_endpoint(request):  # type: ignore[no-untyped-def]
    return [LeverDefinitionOut(**row) for row in catalog_as_dicts()]


@router.get("/simulation/baseline/latest")
@require_permission("simulation.view_simbaseline")
def latest_baseline_endpoint(request):  # type: ignore[no-untyped-def]
    baseline = SimBaseline.objects.filter(tenant=_tenant(request)).order_by("-extracted_at").first()
    if baseline is None:
        return JsonResponse({"detail": _("Aucun socle de simulation n'existe encore.")}, status=404)
    return _serialize_baseline(baseline)


@router.post("/simulation/baseline/refresh")
@require_permission("simulation.add_simbaseline")
def refresh_baseline_endpoint(request):  # type: ignore[no-untyped-def]
    try:
        task_id = refresh_baseline(_tenant(request), user=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"task_id": task_id}


@router.get("/simulation/scenarios")
@require_permission("simulation.view_simscenario")
def list_scenarios_endpoint(request):  # type: ignore[no-untyped-def]
    scenarios = list_scenarios(_tenant(request), request.auth)
    return {"results": [_serialize_scenario(s) for s in scenarios[:200]]}


@router.post("/simulation/scenarios")
@require_permission("simulation.add_simscenario")
def create_scenario_endpoint(request, payload: ScenarioCreateIn):  # type: ignore[no-untyped-def]
    baseline = get_object_or_404(SimBaseline, id=payload.baseline_id)
    try:
        scenario = create_scenario(
            _tenant(request),
            baseline=baseline,
            name=payload.name,
            description=payload.description,
            is_shared=payload.is_shared,
            levers=payload.levers,
            owner=request.auth,
            client_computed_indicators=payload.client_computed_indicators,
            user=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_scenario(scenario)


@router.get("/simulation/scenarios/{scenario_id}")
@require_permission("simulation.view_simscenario")
def get_scenario_endpoint(request, scenario_id: str):  # type: ignore[no-untyped-def]
    scenario = get_object_or_404(SimScenario.objects.select_related("owner"), id=scenario_id)
    try:
        assert_can_view_scenario(scenario, request.auth)
    except PermissionDenied as exc:
        return JsonResponse({"detail": str(exc)}, status=403)
    return _serialize_scenario(scenario)


@router.put("/simulation/scenarios/{scenario_id}")
@require_permission("simulation.change_simscenario")
def update_scenario_endpoint(request, scenario_id: str, payload: ScenarioUpdateIn):  # type: ignore[no-untyped-def]
    scenario = get_object_or_404(SimScenario, id=scenario_id)
    try:
        update_scenario(
            scenario,
            levers=payload.levers,
            user=request.auth,
            name=payload.name,
            description=payload.description,
            is_shared=payload.is_shared,
            client_computed_indicators=payload.client_computed_indicators,
        )
    except PermissionDenied as exc:
        return JsonResponse({"detail": str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_scenario(scenario)


@router.post("/simulation/scenarios/{scenario_id}/archive")
@require_permission("simulation.change_simscenario")
def archive_scenario_endpoint(request, scenario_id: str):  # type: ignore[no-untyped-def]
    scenario = get_object_or_404(SimScenario, id=scenario_id)
    try:
        archive_scenario(scenario, user=request.auth)
    except PermissionDenied as exc:
        return JsonResponse({"detail": str(exc)}, status=403)
    return {"status": "archived"}


@router.get("/simulation/scenarios/{scenario_id}/sensitivity", response=list[SensitivityRowOut])
@require_permission("simulation.view_simscenario")
def sensitivity_endpoint(request, scenario_id: str):  # type: ignore[no-untyped-def]
    scenario = get_object_or_404(SimScenario, id=scenario_id)
    try:
        assert_can_view_scenario(scenario, request.auth)
    except PermissionDenied as exc:
        return JsonResponse({"detail": str(exc)}, status=403)
    baseline_data = deserialize_baseline_data(scenario.baseline)
    rankings = rank_levers_by_sensitivity(baseline_data, scenario.levers)
    return [
        SensitivityRowOut(
            code=row["code"],
            label=row["label"],
            family=row["family"],
            delta_resultat_mga=float(row["delta_resultat_mga"]),
        )
        for row in rankings
    ]


@router.post("/simulation/compare", response=list[ScenarioComparisonRowOut])
@require_permission("simulation.view_simscenario")
def compare_endpoint(request, payload: CompareIn):  # type: ignore[no-untyped-def]
    try:
        rows = compare_scenarios(request.auth, payload.scenario_ids)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return [ScenarioComparisonRowOut(**row) for row in rows]


@router.post("/simulation/ai/apply")
@require_permission("simulation.add_simscenario")
def apply_ai_proposal_endpoint(request, payload: AiProposeIn):  # type: ignore[no-untyped-def]
    """Action HUMAINE et authentifiée qui conserve, dans la bibliothèque de
    scénarios, une proposition déjà calculée par l'outil IA en lecture
    seule (`services.public.preview_indicators_for_levers`, cf. SIM-8) —
    jamais appelée automatiquement par le tool lui-même."""
    baseline = get_object_or_404(SimBaseline, id=payload.baseline_id)
    try:
        scenario = apply_ai_proposed_levers(
            _tenant(request),
            baseline=baseline,
            nl_request=payload.nl_request,
            proposed_levers=payload.proposed_levers,
            owner=request.auth,
            user=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_scenario(scenario)
