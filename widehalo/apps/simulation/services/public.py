"""Contrat public de l'app `simulation` — seule surface que d'autres apps
métier auraient le droit d'importer (cf. tests/architecture/
test_module_boundaries.py). Aucun consommateur cross-app aujourd'hui —
même « graine » que `apps.pos.services.public.get_session_cash_summary` :
prête pour un futur module Phase 2 qui voudrait s'appuyer sur le moteur
de simulation déjà livré en Phase 1 (cahier Phase 1 §2.3, colonne Phase 2 :
« Forecast... s'appuiera sur le moteur de simulation livré en Phase 1 »)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.core.models.tenant import Tenant
from apps.simulation.levers import catalog_as_dicts, clamp_levers
from apps.simulation.models import SimBaseline, SimScenario
from apps.simulation.services.baseline import deserialize_baseline_data
from apps.simulation.services.engine import compute_indicators


def get_latest_baseline_id(tenant: Tenant) -> UUID | None:
    baseline = SimBaseline.objects.filter(tenant=tenant).order_by("-extracted_at").first()
    return baseline.id if baseline else None


def get_scenario_summary(scenario_id: UUID) -> dict[str, Any] | None:
    scenario = SimScenario.objects.filter(id=scenario_id, is_active=True).first()
    if scenario is None:
        return None
    return {
        "id": str(scenario.id),
        "name": scenario.name,
        "levers": scenario.levers,
        "indicators": scenario.computed_indicators,
        "is_shared": scenario.is_shared,
    }


def get_lever_catalog() -> list[dict[str, Any]]:
    return catalog_as_dicts()


def preview_indicators_for_levers(
    tenant: Tenant, *, levers: dict[str, Any], as_of_date: dt.date | None = None
) -> dict[str, Any] | None:
    """Calcul EN LECTURE SEULE (aucune écriture, aucun `SimScenario` créé)
    des indicateurs pour un jeu de leviers donné, à partir du dernier
    `SimBaseline` du tenant — utilisé par l'outil IA `simulation.propose_
    scenario` (SIM-8, cf. `services.ai_data_query_registration`). Renvoie
    `None` si aucun socle n'a encore été construit pour ce tenant."""
    del as_of_date  # reserve pour un futur choix explicite de socle historique
    baseline = SimBaseline.objects.filter(tenant=tenant).order_by("-extracted_at").first()
    if baseline is None:
        return None
    baseline_data = deserialize_baseline_data(baseline)
    clamped = clamp_levers(levers)
    indicators = compute_indicators(baseline_data, clamped)
    return {
        "baseline_id": str(baseline.id),
        "baseline_extracted_at": baseline.extracted_at.isoformat(),
        "levers_applied": _decimal_to_str(clamped),
        "indicators": _decimal_to_str(indicators),
    }


def _decimal_to_str(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _decimal_to_str(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_decimal_to_str(val) for val in value]
    return value
