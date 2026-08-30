"""AI7 (module `ai`) — registre central de regles d'advisor d'actions,
meme patron que `test_anomaly_registry.py`/`test_insight_source_registry.
py`."""

from __future__ import annotations

from apps.core.services.advisor_rule_registry import (
    RecommendationCandidate,
    get_advisor_rule,
    list_advisor_rules,
    list_advisor_rules_for_module,
    register_advisor_rule,
)


def _noop_rule(tenant_id: str, action: str, role_code: str) -> list[RecommendationCandidate]:
    return []


def test_register_and_get_rule() -> None:
    register_advisor_rule("test.noop", module="test", label="No-op", function=_noop_rule)
    rule = get_advisor_rule("test.noop")
    assert rule is not None
    assert rule.module == "test"
    assert rule.function is _noop_rule


def test_register_is_idempotent_replaces_entry() -> None:
    register_advisor_rule("test.replace", module="test", label="V1", function=_noop_rule)
    register_advisor_rule("test.replace", module="test", label="V2", function=_noop_rule)
    rule = get_advisor_rule("test.replace")
    assert rule is not None
    assert rule.label == "V2"


def test_unknown_rule_returns_none() -> None:
    assert get_advisor_rule("does.not.exist") is None


def test_recommendation_candidate_target_action_code_defaults_to_empty() -> None:
    candidate = RecommendationCandidate(label="Label", target_module="test")
    assert candidate.target_action_code == ""


def test_list_advisor_rules_is_sorted_by_code() -> None:
    register_advisor_rule("test.zzz", module="test", label="Z", function=_noop_rule)
    register_advisor_rule("test.aaa", module="test", label="A", function=_noop_rule)
    codes = [r.code for r in list_advisor_rules()]
    assert codes == sorted(codes)


def test_list_advisor_rules_for_module_filters_by_module() -> None:
    register_advisor_rule("test.mod_a", module="test_mod_a", label="A", function=_noop_rule)
    register_advisor_rule("test.mod_b", module="test_mod_b", label="B", function=_noop_rule)
    matching = list_advisor_rules_for_module("test_mod_a")
    assert [r.code for r in matching] == ["test.mod_a"]
