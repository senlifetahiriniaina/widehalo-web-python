"""Schémas django-ninja de l'API `simulation` (§13.6)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ninja import Schema


class LeverDefinitionOut(Schema):
    code: str
    family: str
    label: str
    unit: str
    min: float
    max: float
    default: float


class BaselineOut(Schema):
    id: str
    extracted_at: dt.datetime
    period_start: dt.date
    period_end: dt.date
    as_of_date: dt.date
    regulatory_param_version: dict[str, Any]
    open_items_total_count: int
    open_items_included_count: int
    degraded: bool


class ScenarioCreateIn(Schema):
    baseline_id: str
    name: str
    description: str = ""
    is_shared: bool = False
    levers: dict[str, float]
    client_computed_indicators: dict[str, Any] | None = None


class ScenarioUpdateIn(Schema):
    name: str | None = None
    description: str | None = None
    is_shared: bool | None = None
    levers: dict[str, float]
    client_computed_indicators: dict[str, Any] | None = None


class ScenarioOut(Schema):
    id: str
    baseline_id: str
    name: str
    description: str
    owner_id: str
    owner_email: str
    is_shared: bool
    ai_generated: bool
    ai_request_text: str
    levers: dict[str, Any]
    indicators: dict[str, Any]
    created_at: dt.datetime
    updated_at: dt.datetime


class CompareIn(Schema):
    scenario_ids: list[str]


class ScenarioComparisonRowOut(Schema):
    id: str
    name: str
    owner_id: str
    is_shared: bool
    levers: dict[str, Any]
    indicators: dict[str, Any]


class SensitivityRowOut(Schema):
    code: str
    label: str
    family: str
    delta_resultat_mga: float


class AiProposeIn(Schema):
    baseline_id: str
    nl_request: str
    proposed_levers: dict[str, float]
