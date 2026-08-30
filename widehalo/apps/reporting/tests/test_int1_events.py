"""INT1 (chantier interactivite native inter-modules) : evenement
`reporting.job_failed`, publie par `services/engine.py::_run_job_sync`
(branche echec) — absent jusqu'ici (verifie par lecture directe ; le
succes publiait deja une notification directe, `reporting.job_done`, mais
l'echec ne publiait rien du tout)."""

from __future__ import annotations

import pytest

from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import register_report
from apps.core.tests.utils import use_tenant
from apps.reporting.models import RptJob
from apps.reporting.services.engine import generate_report

pytestmark = pytest.mark.django_db


def _rows_boom(params: dict, actor) -> list[dict]:  # noqa: ANN001
    raise RuntimeError("boom-int1")


def test_generate_report_failure_publishes_job_failed() -> None:
    tenant = Tenant.objects.create(code="RPT-INT1-ENGINE", name="Reporting INT1 Engine Tenant")
    user = User.objects.create_user(
        email="rpt-int1-engine@example.com", password="Str0ngPassw0rd!23"
    )
    register_report(
        code="RPT-TEST-INT1-FAIL",
        module="core",
        label="Fail INT1",
        permission="core.view_tenant",
        render_rows=_rows_boom,
    )
    with use_tenant(tenant.id):
        job = generate_report(
            code="RPT-TEST-INT1-FAIL",
            params={},
            format="json",
            lang="fr",
            actor=user,
            tenant_id=str(tenant.id),
        )
    assert job.state == RptJob.STATE_FAILED

    event = EventLog.objects.get(event_type="reporting.job_failed", tenant_id=str(tenant.id))
    assert event.payload["job_id"] == str(job.id)
    assert "boom-int1" in event.payload["error_message"]
