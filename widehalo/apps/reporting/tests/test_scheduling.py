"""REP3 : `apps.reporting.services.scheduling` — RPT-7. Phase 3 §5 (audit,
decision P5) : `run_schedule` revalide desormais la permission du rapport
cible a CHAQUE execution (createur ET destinataires), pas seulement a la
creation de la planification — `_grant` (meme patron que
`apps.reporting.tests.test_api._grant`) octroie explicitement cette
permission aux utilisateurs de test qui doivent la conserver."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Group, Permission
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


def _grant(user: User, *, app_label: str, codename: str) -> None:
    group, _ = Group.objects.get_or_create(name=f"rpt-sched-test-{app_label}-{codename}")
    group.permissions.add(
        *Permission.objects.filter(content_type__app_label=app_label, codename=codename)
    )
    user.groups.add(group)


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
    """Test d'acceptance §5.11.7 n°4 : "planifier un rapport hebdomadaire"
    (RPT-7) — verifie generation + envoi e-mail + avancement de
    `next_run_at` pour une frequence `FREQUENCY_WEEKLY`."""
    register_report(
        code="RPT-TEST-SCHEDULE",
        module="core",
        label="Test schedule",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-SCHED", name="Reporting Schedule Tenant")
    creator = User.objects.create_user(
        email="rpt-sched-creator@example.com", password="Str0ngPassw0rd!23"
    )
    recipient = User.objects.create_user(
        email="rpt-sched-to@example.com", password="Str0ngPassw0rd!23"
    )
    _grant(creator, app_label="core", codename="view_tenant")
    _grant(recipient, app_label="core", codename="view_tenant")
    with use_tenant(tenant.id):
        schedule = RptSchedule.objects.create(
            tenant=tenant,
            name="Hebdo test",
            report_code="RPT-TEST-SCHEDULE",
            format="csv",
            frequency=RptSchedule.FREQUENCY_WEEKLY,
            next_run_at=timezone.now(),
            created_by=creator,
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
    creator = User.objects.create_user(
        email="rpt-sched-due-creator@example.com", password="Str0ngPassw0rd!23"
    )
    _grant(creator, app_label="core", codename="view_tenant")
    with use_tenant(tenant.id):
        due = RptSchedule.objects.create(
            tenant=tenant,
            name="Due",
            report_code="RPT-TEST-SCHEDULE-DUE",
            format="json",
            frequency=RptSchedule.FREQUENCY_DAILY,
            next_run_at=timezone.now() - dt.timedelta(hours=1),
            created_by=creator,
        )
        not_due = RptSchedule.objects.create(
            tenant=tenant,
            name="Not due",
            report_code="RPT-TEST-SCHEDULE-DUE",
            format="json",
            frequency=RptSchedule.FREQUENCY_DAILY,
            next_run_at=timezone.now() + dt.timedelta(days=1),
            created_by=creator,
        )
        disabled_due = RptSchedule.objects.create(
            tenant=tenant,
            name="Disabled",
            report_code="RPT-TEST-SCHEDULE-DUE",
            format="json",
            frequency=RptSchedule.FREQUENCY_DAILY,
            enabled=False,
            next_run_at=timezone.now() - dt.timedelta(hours=1),
            created_by=creator,
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


def test_run_schedule_disables_itself_when_creator_no_longer_has_permission() -> None:
    """Audit Phase 3 §5 (decision P5) : la permission n'est pas revalidee
    qu'a la creation — un `created_by` sans (ou qui n'a plus) la permission
    du rapport cible fait desactiver la planification plutot que de
    continuer a l'executer indefiniment en silence. Aucun rapport n'est
    genere, aucun e-mail envoye, `last_run_at` n'avance pas."""
    register_report(
        code="RPT-TEST-SCHEDULE-NOPERM",
        module="core",
        label="Test schedule sans permission",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-SCHED-NOPERM", name="Reporting Schedule No Perm")
    recipient = User.objects.create_user(
        email="rpt-sched-noperm-to@example.com", password="Str0ngPassw0rd!23"
    )
    _grant(recipient, app_label="core", codename="view_tenant")
    with use_tenant(tenant.id):
        # `created_by=None` (jamais defini, ou compte supprime depuis —
        # `on_delete=SET_NULL` sur `BaseModel.created_by`) : aucune
        # permission ne peut etre confirmee pour cette planification.
        schedule = RptSchedule.objects.create(
            tenant=tenant,
            name="Sans createur autorise",
            report_code="RPT-TEST-SCHEDULE-NOPERM",
            format="csv",
            frequency=RptSchedule.FREQUENCY_WEEKLY,
            next_run_at=timezone.now(),
            created_by=None,
        )
        schedule.recipients.add(recipient)

        run_schedule(schedule)
        schedule.refresh_from_db()

    assert schedule.enabled is False
    assert schedule.last_run_at is None
    assert len(mail.outbox) == 0


def test_run_schedule_excludes_recipients_who_lost_permission() -> None:
    """Audit Phase 3 §5 (decision P5) : « destinataires non revérifiés » —
    un destinataire qui n'a lui-meme pas (ou plus) la permission du
    rapport cible ne recoit pas l'e-mail, meme si le createur de la
    planification l'a bien conservee et que d'autres destinataires
    restent autorises."""
    register_report(
        code="RPT-TEST-SCHEDULE-RECIP",
        module="core",
        label="Test schedule destinataires",
        permission="core.view_tenant",
        render_rows=_rows,
        fields=("a",),
    )
    tenant = Tenant.objects.create(code="RPT-SCHED-RECIP", name="Reporting Schedule Recipients")
    creator = User.objects.create_user(
        email="rpt-sched-recip-creator@example.com", password="Str0ngPassw0rd!23"
    )
    authorized_recipient = User.objects.create_user(
        email="rpt-sched-recip-ok@example.com", password="Str0ngPassw0rd!23"
    )
    unauthorized_recipient = User.objects.create_user(
        email="rpt-sched-recip-no@example.com", password="Str0ngPassw0rd!23"
    )
    _grant(creator, app_label="core", codename="view_tenant")
    _grant(authorized_recipient, app_label="core", codename="view_tenant")
    with use_tenant(tenant.id):
        schedule = RptSchedule.objects.create(
            tenant=tenant,
            name="Destinataires mixtes",
            report_code="RPT-TEST-SCHEDULE-RECIP",
            format="csv",
            frequency=RptSchedule.FREQUENCY_WEEKLY,
            next_run_at=timezone.now(),
            created_by=creator,
        )
        schedule.recipients.add(authorized_recipient, unauthorized_recipient)

        run_schedule(schedule)
        schedule.refresh_from_db()

    assert schedule.enabled is True
    assert schedule.last_run_at is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [authorized_recipient.email]
