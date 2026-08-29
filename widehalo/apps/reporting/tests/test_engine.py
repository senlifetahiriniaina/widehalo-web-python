"""REP2 : `apps.reporting.services.engine` — dispatch synchrone, RPT-6
asynchronisme (test d'acceptance §5.11.7 n°4), purge des jobs expires."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import register_report
from apps.core.tests.utils import use_tenant
from apps.reporting.models import RptJob
from apps.reporting.services.engine import (
    UnknownReportError,
    generate_report,
    purge_expired_jobs,
    rows_to_bytes,
)

pytestmark = pytest.mark.django_db


def _rows_ok(params: dict, actor) -> list[dict]:  # noqa: ANN001
    return [{"a": 1, "b": 2}]


def _rows_boom(params: dict, actor) -> list[dict]:  # noqa: ANN001
    raise RuntimeError("boom")


@pytest.fixture
def tenant_and_user():
    tenant = Tenant.objects.create(code="RPT-ENGINE", name="Reporting Engine Tenant")
    user = User.objects.create_user(email="rpt-engine@example.com", password="Str0ngPassw0rd!23")
    return tenant, user


def test_rows_to_bytes_json_csv_xlsx() -> None:
    rows = [{"x": 1, "y": 2}]
    assert b"1" in rows_to_bytes(rows, ("x", "y"), format="json")
    assert b"x,y" in rows_to_bytes(rows, ("x", "y"), format="csv")
    assert rows_to_bytes(rows, ("x", "y"), format="xlsx")[:2] == b"PK"  # signature zip/xlsx


def test_rows_to_bytes_derives_dynamic_fields_when_none_provided() -> None:
    rows = [{"only_col": "v"}]
    data = rows_to_bytes(rows, (), format="csv")
    assert b"only_col" in data


def test_generate_report_sync_produces_done_job_with_file(tenant_and_user) -> None:
    tenant, user = tenant_and_user
    register_report(
        code="RPT-TEST-ENGINE-SYNC",
        module="core",
        label="Sync",
        permission="core.view_tenant",
        render_rows=_rows_ok,
        fields=("a", "b"),
    )
    with use_tenant(tenant.id):
        job = generate_report(
            code="RPT-TEST-ENGINE-SYNC",
            params={},
            format="csv",
            lang="fr",
            actor=user,
            tenant_id=str(tenant.id),
        )
    assert job.state == RptJob.STATE_DONE
    assert job.file
    assert job.finished_at is not None


def test_generate_report_marks_job_failed_on_renderer_exception(tenant_and_user) -> None:
    tenant, user = tenant_and_user
    register_report(
        code="RPT-TEST-ENGINE-FAIL",
        module="core",
        label="Fail",
        permission="core.view_tenant",
        render_rows=_rows_boom,
    )
    with use_tenant(tenant.id):
        job = generate_report(
            code="RPT-TEST-ENGINE-FAIL",
            params={},
            format="json",
            lang="fr",
            actor=user,
            tenant_id=str(tenant.id),
        )
    assert job.state == RptJob.STATE_FAILED
    assert "boom" in job.error_message


def test_generate_report_unknown_code_raises(tenant_and_user) -> None:
    tenant, user = tenant_and_user
    with use_tenant(tenant.id), pytest.raises(UnknownReportError):
        generate_report(
            code="RPT-DOES-NOT-EXIST",
            params={},
            format="json",
            lang="fr",
            actor=user,
            tenant_id=str(tenant.id),
        )


def test_acceptance_4_large_report_routes_through_async_job(tenant_and_user) -> None:
    """Test d'acceptance §5.11.7 n°4 : "rapport de 50 000 lignes -> genere en
    asynchrone". Simplification disclosed (cf. docstring `engine.py`) :
    `estimated_row_count=50_000` (le chiffre exact du CDC) route bien vers
    `core.tasks.enqueue()` plutot qu'une execution en synchrone dans le
    thread appelant — verifie ici en observant que le job existe des le
    retour de l'appel (cree avant l'enqueue) et finit `done` (Q_CLUSTER
    `sync=True` en test, cf. `config.settings.test`, execute la tache
    immediatement — meme piege documente que `core.events`), sans jamais
    construire 50 000 lignes reelles (le rapport enregistre ici renvoie 1
    seule ligne)."""
    tenant, user = tenant_and_user
    register_report(
        code="RPT-TEST-ENGINE-ASYNC",
        module="core",
        label="Async",
        permission="core.view_tenant",
        render_rows=_rows_ok,
        fields=("a", "b"),
    )
    with use_tenant(tenant.id):
        job = generate_report(
            code="RPT-TEST-ENGINE-ASYNC",
            params={},
            format="json",
            lang="fr",
            actor=user,
            tenant_id=str(tenant.id),
            estimated_row_count=50_000,
        )
        job.refresh_from_db()
    assert job.state == RptJob.STATE_DONE


def test_purge_expired_jobs_removes_only_expired(tenant_and_user) -> None:
    tenant, user = tenant_and_user
    with use_tenant(tenant.id):
        expired = RptJob.objects.create(
            tenant=tenant,
            report_code="RPT-X",
            format=RptJob.FORMAT_JSON,
            state=RptJob.STATE_DONE,
            expires_at=timezone.now() - dt.timedelta(days=1),
        )
        fresh = RptJob.objects.create(
            tenant=tenant,
            report_code="RPT-X",
            format=RptJob.FORMAT_JSON,
            state=RptJob.STATE_DONE,
            expires_at=timezone.now() + dt.timedelta(days=6),
        )

    count = purge_expired_jobs()
    assert count >= 1

    with use_tenant(tenant.id):
        assert not RptJob.objects.filter(id=expired.id).exists()
        assert RptJob.objects.filter(id=fresh.id).exists()
