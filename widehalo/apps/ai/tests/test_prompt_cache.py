"""AI6 — verifie le wrapper generique de cache de prompts, independamment
de son seul consommateur reel actuel (`contextual_assistant`, AI2)."""

from __future__ import annotations

from django.core.cache import cache

from apps.ai.services.prompt_cache import (
    build_cache_key,
    build_prompt_cache_key,
    get_cached,
    hash_payload,
    set_cached,
)


def setup_function() -> None:
    cache.clear()


def teardown_function() -> None:
    cache.clear()


def test_build_cache_key_joins_parts_with_colon() -> None:
    assert build_cache_key("ai_assist", "sales", "list", "fr") == "ai_assist:sales:list:fr"


def test_hash_payload_is_stable_regardless_of_key_order() -> None:
    assert hash_payload({"a": 1, "b": 2}) == hash_payload({"b": 2, "a": 1})


def test_hash_payload_differs_for_different_content() -> None:
    assert hash_payload({"a": 1}) != hash_payload({"a": 2})


def test_build_prompt_cache_key_differs_by_model_and_prompt() -> None:
    key_a = build_prompt_cache_key("ai_advisor", "deepseek-chat", "hello")
    key_b = build_prompt_cache_key("ai_advisor", "deepseek-chat", "world")
    key_c = build_prompt_cache_key("ai_advisor", "kimi-k2", "hello")
    assert key_a != key_b
    assert key_a != key_c
    assert key_a.startswith("ai_advisor:")


def test_get_cached_returns_none_when_absent() -> None:
    assert get_cached("does-not-exist") is None


def test_set_then_get_round_trips() -> None:
    key = build_cache_key("test_feature", "x")
    set_cached(key, {"value": 42})
    assert get_cached(key) == {"value": 42}


def test_set_cached_respects_custom_ttl(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_set(key: str, value: object, timeout: int) -> None:
        captured["key"] = key
        captured["value"] = value
        captured["timeout"] = timeout

    monkeypatch.setattr("apps.ai.services.prompt_cache.cache.set", _fake_set)
    set_cached("k", "v", ttl_seconds=60)
    assert captured == {"key": "k", "value": "v", "timeout": 60}
