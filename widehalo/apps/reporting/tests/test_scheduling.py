"""REP3 : `apps.reporting.services.scheduling` — RPT-7."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core import mail
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import register_report
from apps.core.tests.utils import use_tenant
from apps.reporting.models import RptSchedule
from apps.reporting.services.scheduling import compute_next_run_at, run_due_schedules, run_schedule

pytestmark = pytest.mark.django_db


def _rows(params: dict, actor) -> list[dict]:  # noqa: ANN001
    return [{"a": 1}]


@pytest.mark.parametrize(
    "frequency,expected_delta",
    [
        (RptSchedule.FREQUENCY_DAILY, dt.timedelta(days=1)),
        (RptSchedule.FREQUENCY_WEEKLY, dt.timedelta(weeks=1)),
        (RptSchedule.FREQUENCY_MONTHLY, dt.timedelta(days=30)),
    ],
)
def test_compute_next_run_at(frequency, expected_delta) -> None:  # noqa: ANN001
    now = timezone.now()
    assert compute_next_run_at(frequency, after=now) == now + expected_delta


def test_run_schedule_generates_report_emails_recipients_and_advances_next_run() -> None:
    register_report(
        code="RPT-TEST-SCHEDULE",
        module="core",
        label="Test schedule",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-SCHED", name="Reporting Schedule Tenant")
    recipient = User.objects.create_user(
        email="rpt-sched-to@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        schedule = RptSchedule.objects.create(
            tenant=tenant,
            name="Hebdo test",
            report_code="RPT-TEST-SCHEDULE",
            format="csv",
            frequency=RptSchedule.FREQUENCY_WEEKLY,
            next_run_at=timezone.now(),
        )
        schedule.recipients.add(recipient)

        original_next_run = schedule.next_run_at
        run_schedule(schedule)
        schedule.refresh_from_db()

    assert schedule.last_run_at is not None
    assert schedule.next_run_at > original_next_run
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [recipient.email]
    assert mail.outbox[0].attachments


def test_run_due_schedules_only_runs_due_and_enabled() -> None:
    register_report(
        code="RPT-TEST-SCHEDULE-DUE",
        module="core",
        label="Test schedule due",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-SCHED-DUE", name="Reporting Schedule Due Tenant")
    with use_tenant(tenant.id):
        due = RptSchedule.objects.create(
            tenant=tenant,
            name="Due",
            report_code="RPT-TEST-SCHEDULE-DUE",
            format="json",
            frequency=RptSchedule.FREQUENCY_DAILY,
            next_run_at=timezone.now() - dt.timedelta(hours=1),
        )
        not_due = RptSchedule.objects.create(
            tenant=tenant,
            name="Not due",
            report_code="RPT-TEST-SCHEDULE-DUE",
            format="json",
            frequency=RptSchedule.FREQUENCY_DAILY,
            next_run_at=timezone.now() + dt.timedelta(days=1),
        )
        disabled_due = RptSchedule.objects.create(
            tenant=tenant,
            name="Disabled",
            report_code="RPT-TEST-SCHEDULE-DUE",
            format="json",
            frequency=RptSchedule.FREQUENCY_DAILY,
            enabled=False,
            next_run_at=timezone.now() - dt.timedelta(hours=1),
        )

    count = run_due_schedules()
    assert count >= 1

    with use_tenant(tenant.id):
        due.refresh_from_db()
        not_due.refresh_from_db()
        disabled_due.refresh_from_db()
        assert due.last_run_at is not None
        assert not_due.last_run_at is None
        assert disabled_due.last_run_at is None
