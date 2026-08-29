"""Tests PJ8 (suivi du temps, `services/time_tracking.py`) — cf. plan,
section « Module `projects` », etape PJ8."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjTimeEntry
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task
from apps.projects.services.time_tracking import (
    get_time_report,
    get_unbilled_billable_hours,
    log_manual_time_entry,
    start_timer,
    stop_timer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def time_tracking_setup():
    tenant = Tenant.objects.create(code="PRJ-TIME", name="Projects Time Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="projects-time@example.com", password="Str0ngPassw0rd!23"
        )
        other_user = User.objects.create_user(
            email="projects-time-other@example.com", password="Str0ngPassw0rd!23"
        )
        project = create_project(tenant, name="Projet chronometre")
        task = create_task(tenant, project=project)
        return tenant, user, other_user, project, task


# --- start_timer / stop_timer -----------------------------------------------------


def test_start_and_stop_timer_computes_duration(time_tracking_setup) -> None:
    tenant, user, _other, _project, task = time_tracking_setup
    with use_tenant(tenant.id):
        entry = start_timer(task, user)
        assert entry.stopped_at is None
        assert entry.duration_minutes == 0

        # Force un creneau connu (30 minutes) pour verifier le calcul exact.
        started_at = timezone.now() - dt.timedelta(minutes=30)
        entry.started_at = started_at
        entry.save(update_fields=["started_at"])

        stopped = stop_timer(entry, user)
        assert stopped.stopped_at is not None
        assert stopped.duration_minutes == 30


def test_start_timer_refuses_second_active_timer_for_same_user(time_tracking_setup) -> None:
    tenant, user, _other, project, task = time_tracking_setup
    with use_tenant(tenant.id):
        start_timer(task, user)
        other_task = create_task(tenant, project=project)

        with pytest.raises(ValidationError):
            start_timer(other_task, user)
        assert PrjTimeEntry.objects.filter(user=user, stopped_at__isnull=True).count() == 1


def test_stop_timer_refuses_already_stopped(time_tracking_setup) -> None:
    tenant, user, _other, _project, task = time_tracking_setup
    with use_tenant(tenant.id):
        entry = start_timer(task, user)
        stop_timer(entry, user)

        with pytest.raises(ValidationError):
            stop_timer(entry, user)


def test_stop_timer_refuses_other_users_timer(time_tracking_setup) -> None:
    """RBAC N3 : un utilisateur ne peut arreter que SON PROPRE chrono."""
    tenant, user, other_user, _project, task = time_tracking_setup
    with use_tenant(tenant.id):
        entry = start_timer(task, user)

        with pytest.raises(ValidationError):
            stop_timer(entry, other_user)
        entry.refresh_from_db()
        assert entry.stopped_at is None


# --- log_manual_time_entry --------------------------------------------------------


def test_log_manual_time_entry_computes_duration(time_tracking_setup) -> None:
    tenant, user, _other, _project, task = time_tracking_setup
    with use_tenant(tenant.id):
        started_at = timezone.now() - dt.timedelta(hours=2)
        stopped_at = started_at + dt.timedelta(hours=2)

        entry = log_manual_time_entry(
            task, user, started_at=started_at, stopped_at=stopped_at, note="Saisie a posteriori"
        )

        assert entry.duration_minutes == 120
        assert entry.stopped_at == stopped_at
        assert entry.billable is True
        assert entry.note == "Saisie a posteriori"


def test_log_manual_time_entry_refuses_stopped_before_started(time_tracking_setup) -> None:
    tenant, user, _other, _project, task = time_tracking_setup
    with use_tenant(tenant.id):
        now = timezone.now()

        with pytest.raises(ValidationError):
            log_manual_time_entry(
                task, user, started_at=now, stopped_at=now - dt.timedelta(hours=1)
            )


# --- get_time_report ---------------------------------------------------------------


def test_get_time_report_aggregates_by_user(time_tracking_setup) -> None:
    tenant, user, other_user, project, task = time_tracking_setup
    with use_tenant(tenant.id):
        now = timezone.now()
        # user : 60 minutes facturables + 30 minutes non facturables.
        log_manual_time_entry(
            task, user, started_at=now - dt.timedelta(hours=1), stopped_at=now, billable=True
        )
        log_manual_time_entry(
            task,
            user,
            started_at=now - dt.timedelta(minutes=30),
            stopped_at=now,
            billable=False,
        )
        # other_user : 45 minutes facturables.
        log_manual_time_entry(
            task,
            other_user,
            started_at=now - dt.timedelta(minutes=45),
            stopped_at=now,
            billable=True,
        )
        # Chrono en cours (non arrete) : ne doit PAS entrer dans le rapport.
        start_timer(task, other_user)

        report = get_time_report(project)
        by_user = {row["user_id"]: row for row in report}

        assert by_user[user.id]["total_minutes"] == 90
        assert by_user[user.id]["billable_minutes"] == 60
        assert by_user[user.id]["billed_minutes"] == 0
        assert by_user[other_user.id]["total_minutes"] == 45
        assert by_user[other_user.id]["billable_minutes"] == 45


def test_get_time_report_filters_by_date_range(time_tracking_setup) -> None:
    tenant, user, _other, project, task = time_tracking_setup
    with use_tenant(tenant.id):
        old_start = dt.datetime(2025, 1, 1, 9, 0, tzinfo=dt.UTC)
        old_stop = dt.datetime(2025, 1, 1, 10, 0, tzinfo=dt.UTC)
        log_manual_time_entry(task, user, started_at=old_start, stopped_at=old_stop)

        recent = timezone.now()
        log_manual_time_entry(
            task, user, started_at=recent - dt.timedelta(minutes=20), stopped_at=recent
        )

        report = get_time_report(project, date_from=dt.date.today())
        assert len(report) == 1
        assert report[0]["total_minutes"] == 20


# --- get_unbilled_billable_hours ---------------------------------------------------


def test_get_unbilled_billable_hours_excludes_non_billable_and_already_billed(
    time_tracking_setup,
) -> None:
    tenant, user, _other, project, task = time_tracking_setup
    with use_tenant(tenant.id):
        now = timezone.now()
        log_manual_time_entry(
            task, user, started_at=now - dt.timedelta(hours=2), stopped_at=now, billable=True
        )
        non_billable = log_manual_time_entry(
            task,
            user,
            started_at=now - dt.timedelta(hours=1),
            stopped_at=now,
            billable=False,
        )
        already_billed = log_manual_time_entry(
            task, user, started_at=now - dt.timedelta(hours=3), stopped_at=now, billable=True
        )
        already_billed.billed = True
        already_billed.save(update_fields=["billed"])

        assert non_billable.billable is False
        assert get_unbilled_billable_hours(project) == 2
