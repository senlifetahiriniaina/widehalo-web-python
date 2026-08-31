"""RPT-7 : planification quotidienne/hebdomadaire/mensuelle d'un rapport +
envoi e-mail aux destinataires. Executee par la commande de management
`run_report_schedules`, SANS cron auto-enregistre — meme discipline que
`run_sales_recurrences`/`run_presence_maintenance` (cf. docstring
`RptSchedule`)."""

from __future__ import annotations

import datetime as dt

from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.reporting.models import RptSchedule
from apps.reporting.services.engine import generate_report

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
}


def compute_next_run_at(frequency: str, *, after: dt.datetime | None = None) -> dt.datetime:
    reference = after or timezone.now()
    if frequency == RptSchedule.FREQUENCY_DAILY:
        return reference + dt.timedelta(days=1)
    if frequency == RptSchedule.FREQUENCY_WEEKLY:
        return reference + dt.timedelta(weeks=1)
    if frequency == RptSchedule.FREQUENCY_MONTHLY:
        return reference + dt.timedelta(days=30)
    raise ValueError(_("fréquence de planification inconnue : %(freq)s") % {"freq": frequency})


def _send_schedule_email(schedule: RptSchedule, data: bytes) -> None:
    recipients = list(schedule.recipients.values_list("email", flat=True))
    if not recipients:
        return
    message = EmailMessage(
        subject=_("Rapport planifie : %(name)s") % {"name": schedule.name},
        body=_("Veuillez trouver ci-joint le rapport planifie « %(name)s ».")
        % {"name": schedule.name},
        to=recipients,
    )
    message.attach(
        f"{schedule.report_code}.{schedule.format}", data, _CONTENT_TYPES[schedule.format]
    )
    message.send(fail_silently=False)


def run_schedule(schedule: RptSchedule) -> None:
    """Genere le rapport (toujours en synchrone : une planification n'a pas
    de requete web a liberer, `estimated_row_count` reste donc None) et
    l'envoie par e-mail aux destinataires, puis avance `next_run_at`."""
    job = generate_report(
        code=schedule.report_code,
        params=schedule.params,
        format=schedule.format,
        lang=schedule.lang,
        actor=None,
        tenant_id=str(schedule.tenant_id),
    )
    if job.file:
        job.file.open("rb")
        try:
            _send_schedule_email(schedule, job.file.read())
        finally:
            job.file.close()

    now = timezone.now()
    schedule.last_run_at = now
    schedule.next_run_at = compute_next_run_at(schedule.frequency, after=now)
    schedule.save(update_fields=["last_run_at", "next_run_at"])


def run_due_schedules() -> int:
    """Appelee par la commande de management `run_report_schedules` — boucle
    par tenant (RLS, meme discipline que `purge_expired_jobs`)."""
    now = timezone.now()
    count = 0
    for tenant_id in Tenant.objects.values_list("id", flat=True):
        with activate_tenant(tenant_id):
            due = list(RptSchedule.objects.filter(enabled=True, next_run_at__lte=now))
            for schedule in due:
                run_schedule(schedule)
                count += 1
    return count
