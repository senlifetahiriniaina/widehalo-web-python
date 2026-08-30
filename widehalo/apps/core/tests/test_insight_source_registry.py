"""AI5 (module `ai`) — registre central de sources d'insights proactifs,
meme patron que `test_anomaly_registry.py`."""

from __future__ import annotations

from apps.core.services.insight_source_registry import (
    InsightCandidate,
    get_insight_source,
    list_insight_sources,
    register_insight_source,
)


def _noop_source(tenant_id: str) -> list[InsightCandidate]:
    return []


def test_register_and_get_source() -> None:
    register_insight_source("test.noop", module="test", label="No-op", function=_noop_source)
    source = get_insight_source("test.noop")
    assert source is not None
    assert source.module == "test"
    assert source.function is _noop_source


def test_register_is_idempotent_replaces_entry() -> None:
    register_insight_source("test.replace", module="test", label="V1", function=_noop_source)
    register_insight_source("test.replace", module="test", label="V2", function=_noop_source)
    source = get_insight_source("test.replace")
    assert source is not None
    assert source.label == "V2"


def test_unknown_source_returns_none() -> None:
    assert get_insight_source("does.not.exist") is None


def test_insight_candidate_carries_category_and_sources() -> None:
    def _source(tenant_id: str) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                category="ventes",
                title="Titre",
                body="Corps",
                source_modules=["sales"],
            )
        ]

    candidates = _source("t1")
    assert candidates[0].category == "ventes"
    assert candidates[0].source_modules == ["sales"]


def test_insight_candidate_source_modules_defaults_to_empty_list() -> None:
    candidate = InsightCandidate(category="rh", title="T", body="B")
    assert candidate.source_modules == []


def test_list_insight_sources_is_sorted_by_code() -> None:
    register_insight_source("test.zzz", module="test", label="Z", function=_noop_source)
    register_insight_source("test.aaa", module="test", label="A", function=_noop_source)
    codes = [c.code for c in list_insight_sources()]
    assert codes == sorted(codes)
