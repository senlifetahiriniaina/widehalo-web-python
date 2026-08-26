"""§5.2.5 : chronologie des activites (appel/visite/email/relance/reunion)
attachees a une opportunite. Simple journalisation planifiee/realisee, pas
de moteur de rappel automatique dans ce lot (dependrait de notifications
programmees, hors perimetre CRM)."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from apps.core.models.user import User
from apps.crm.models import CrmActivity, CrmLead


def log_activity(
    lead: CrmLead,
    *,
    activity_type: str,
    subject: str,
    notes: str = "",
    due_at: datetime | None = None,
    assigned_to: User | None = None,
) -> CrmActivity:
    return CrmActivity.objects.create(
        tenant=lead.tenant,
        lead=lead,
        activity_type=activity_type,
        subject=subject,
        notes=notes,
        due_at=due_at,
        assigned_to=assigned_to,
    )


def complete_activity(activity: CrmActivity) -> CrmActivity:
    activity.done_at = timezone.now()
    activity.save(update_fields=["done_at"])
    return activity


def lead_timeline(lead: CrmLead) -> list[CrmActivity]:
    """Chronologie complete (realisees et planifiees), la plus recente en
    tete — `CrmActivity.Meta.ordering` fait deja ce tri."""
    return list(lead.activities.all())
