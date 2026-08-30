"""AI1 (socle module `ai`) — registre central de verifications d'anomalies,
meme patron que `test_automation_registry.py`/`core.services.
reports_registry`."""

from __future__ import annotations

from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    AnomalyCandidate,
    get_anomaly_check,
    list_anomaly_checks,
    register_anomaly_check,
)


def _noop_check(tenant_id: str) -> list[AnomalyCandidate]:
    return []


def test_register_and_get_check() -> None:
    register_anomaly_check("test.noop", module="test", label="No-op", function=_noop_check)
    check = get_anomaly_check("test.noop")
    assert check is not None
    assert check.module == "test"
    assert check.function is _noop_check


def test_register_is_idempotent_replaces_entry() -> None:
    register_anomaly_check("test.replace", module="test", label="V1", function=_noop_check)
    register_anomaly_check("test.replace", module="test", label="V2", function=_noop_check)
    check = get_anomaly_check("test.replace")
    assert check is not None
    assert check.label == "V2"


def test_unknown_check_returns_none() -> None:
    assert get_anomaly_check("does.not.exist") is None


def test_anomaly_candidate_carries_severity_and_target() -> None:
    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="accounting.accbudgetline",
                object_id=tenant_id,
                severity=SEVERITY_HIGH,
                description="Ecart budgetaire",
            )
        ]

    candidates = _check("t1")
    assert candidates[0].severity == SEVERITY_HIGH
    assert candidates[0].content_type_label == "accounting.accbudgetline"


def test_list_anomaly_checks_is_sorted_by_code() -> None:
    register_anomaly_check("test.zzz", module="test", label="Z", function=_noop_check)
    register_anomaly_check("test.aaa", module="test", label="A", function=_noop_check)
    codes = [c.code for c in list_anomaly_checks()]
    assert codes == sorted(codes)
