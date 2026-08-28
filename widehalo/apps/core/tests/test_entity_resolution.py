from __future__ import annotations

from apps.core.services.entity_resolution import (
    ResolutionConfidence,
    ResolutionResult,
    normalize_name,
)


def test_normalize_name_strips_accents_case_and_extra_spaces() -> None:
    assert normalize_name("  Établissement   Éléphant BLEU  ") == "etablissement elephant bleu"


def test_normalize_name_is_stable_on_already_normalized_input() -> None:
    assert normalize_name("etablissement elephant bleu") == "etablissement elephant bleu"


def test_resolution_result_unresolved_has_no_entity_id() -> None:
    result = ResolutionResult(confidence=ResolutionConfidence.UNRESOLVED, entity_id=None)
    assert result.entity_id is None
    assert result.is_placeholder is False


def test_resolution_confidence_values_are_exact_fuzzy_unresolved() -> None:
    assert {c.value for c in ResolutionConfidence} == {"exact", "fuzzy", "unresolved"}
