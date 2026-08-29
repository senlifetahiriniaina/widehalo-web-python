"""REP1 : registre central (`core.services.reports_registry`) — meme
discipline de test que `apps.core.tests.test_event_bus` pour le patron
`core.events`."""

from __future__ import annotations

import pytest

from apps.core.services.reports_registry import get_registered_report, register_report


def test_register_report_requires_at_least_one_renderer() -> None:
    with pytest.raises(ValueError, match="renderer"):
        register_report(
            code="RPT-TEST-EMPTY",
            module="core",
            label="Vide",
            permission="core.view_tenant",
        )


def test_register_and_get_report_round_trips() -> None:
    def _rows(params: dict, actor) -> list[dict]:  # noqa: ANN001
        return [{"a": 1}]

    register_report(
        code="RPT-TEST-ROWS",
        module="core",
        label="Test rows",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    report = get_registered_report("RPT-TEST-ROWS")
    assert report is not None
    assert report.supports_rows()
    assert not report.supports_pdf()
    assert report.render_rows is not None
    assert report.render_rows({}, None) == [{"a": 1}]
