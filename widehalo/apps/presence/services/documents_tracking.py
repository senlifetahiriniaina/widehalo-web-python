"""PR3 : PRS-DOC1 (suivi d'expiration de documents employe — permis,
certifications, visites medicales). Meme patron que
`apps.logistics.services.vehicles.upcoming_document_alerts`/
`notify_document_alert` (RG-LOG-1), transpose a `PrsEmployeeTask
(kind="document")`."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.core.services.notifications import dispatch_notification
from apps.presence.models import PrsEmployee, PrsEmployeeTask

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def add_employee_document(
    employee: PrsEmployee,
    *,
    code: str,
    label: str,
    reference: str = "",
    issue_date: dt.date | None = None,
    expiry_date: dt.date | None = None,
    alert_days_before: int = 30,
) -> PrsEmployeeTask:
    document = PrsEmployeeTask(
        tenant=employee.tenant,
        employee=employee,
        kind=PrsEmployeeTask.KIND_DOCUMENT,
        code=code,
        label=label,
        reference=reference,
        issue_date=issue_date,
        target_date=expiry_date,
        alert_days_before=alert_days_before,
    )
    document.full_clean()
    document.save()
    return document


def upcoming_document_alerts(tenant: Tenant, *, within_days: int = 30) -> list[PrsEmployeeTask]:
    today = timezone.localdate()
    horizon = today + dt.timedelta(days=within_days)
    return list(
        PrsEmployeeTask.objects.filter(
            tenant=tenant,
            kind=PrsEmployeeTask.KIND_DOCUMENT,
            target_date__isnull=False,
            target_date__lte=horizon,
            notified_at__isnull=True,
        ).order_by("target_date")
    )


def notify_document_alert(document: PrsEmployeeTask, *, recipient: User) -> None:
    dispatch_notification(
        recipient,
        "presence.employee_document_expiring",
        {
            "employee_id": str(document.employee_id),
            "label": document.label,
            "expiry_date": document.target_date.isoformat() if document.target_date else None,
        },
        tenant_id=str(document.tenant_id),
    )
    document.notified_at = timezone.now()
    document.save(update_fields=["notified_at"])
