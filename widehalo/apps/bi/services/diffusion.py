"""Diffusion planifiée (BI-7) — envoi par e-mail du contenu d'un `BiReport`
et journalisation systématique de chaque envoi (`BiDiffusionLog`), succès
ou échec — jamais un envoi silencieux.

Diffère de `apps.reporting.services.scheduling.run_schedule` (RPT-7) sur
un point structurant : celui-ci envoie UN SEUL e-mail identique à tous les
destinataires (`RptSchedule.recipients`, sans re-scoping par destinataire) ;
celui-ci RECALCULE le rapport POUR CHAQUE destinataire (son rôle réel
détermine son périmètre réel, BI-6 — deux destinataires peuvent recevoir
des valeurs différentes, cahier §13.1 : « l'interface l'indique ») et
journalise chaque envoi séparément — non réutilisable tel quel, d'où ce
mécanisme parallèle plutôt qu'une extension de `RptSchedule` (cf. docstring
`apps.bi.models`)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.bi.models import BiDiffusionLog, BiReport
from apps.bi.services.query import run_report

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def compute_next_run_at(frequency: str, *, after: dt.datetime | None = None) -> dt.datetime:
    reference = after or timezone.now()
    if frequency == BiReport.FREQUENCY_DAILY:
        return reference + dt.timedelta(days=1)
    if frequency == BiReport.FREQUENCY_WEEKLY:
        return reference + dt.timedelta(weeks=1)
    if frequency == BiReport.FREQUENCY_MONTHLY:
        return reference + dt.timedelta(days=30)
    raise ValueError(_("fréquence de diffusion inconnue : %(freq)s") % {"freq": frequency})


def _format_scope_summary(result: dict[str, Any]) -> str:
    return "; ".join(result["scope_notes"]) if result["scope_notes"] else "périmètre complet"


def _render_summary_body(report: BiReport, result: dict[str, Any]) -> str:
    lines = [f"Rapport « {report.name} »", ""]
    for payload in result["metrics"].values():
        unite = payload["unite"] or "sans unité"
        lines.append(f"{payload['libelle']} ({unite})")
        for row in payload["rows"][:20]:
            dims = ", ".join(f"{k}={v}" for k, v in row.items() if k != "value")
            lines.append(f"  {dims + ': ' if dims else ''}{row['value']}")
    if result["scope_notes"]:
        lines.append("")
        lines.append("Périmètre appliqué :")
        lines.extend(f"- {note}" for note in result["scope_notes"])
    return "\n".join(lines)


def send_report_to_recipient(report: BiReport, recipient: User) -> BiDiffusionLog:
    """Calcule le rapport POUR `recipient` (son rôle réel, BI-6) et le lui
    envoie par e-mail — journalise systématiquement l'issue (BI-7)."""
    try:
        result = run_report(report.tenant, report, recipient)
        message = EmailMessage(
            subject=_("Rapport BI : %(name)s") % {"name": report.name},
            body=_render_summary_body(report, result),
            to=[recipient.email],
        )
        message.send(fail_silently=False)
        return BiDiffusionLog.objects.create(
            tenant=report.tenant,
            report=report,
            recipient=recipient.email,
            channel=report.diffusion_channel,
            scope_summary=_format_scope_summary(result)[:255],
            status=BiDiffusionLog.STATUS_SENT,
            sent_at=timezone.now(),
        )
    except Exception as exc:  # noqa: BLE001 - un echec d'envoi doit etre journalise, pas propage
        return BiDiffusionLog.objects.create(
            tenant=report.tenant,
            report=report,
            recipient=getattr(recipient, "email", "?"),
            channel=report.diffusion_channel,
            status=BiDiffusionLog.STATUS_FAILED,
            sent_at=timezone.now(),
            error_message=str(exc),
        )


def run_due_diffusions(tenant: Tenant) -> int:
    """Commande ops (`management/commands/run_bi_diffusions.py`) : diffuse
    tous les `BiReport` de `tenant` dont `diffusion_next_run_at` est
    échu, à chaque destinataire de `diffusion_recipients` (liste
    d'e-mails), puis avance le jalon. Retourne le nombre d'envois
    journalisés (succès + échecs)."""
    from apps.core.models.user import User

    now = timezone.now()
    count = 0
    reports = BiReport.objects.filter(
        tenant=tenant, diffusion_enabled=True, diffusion_next_run_at__lte=now
    ).exclude(diffusion_frequency="")
    for report in reports:
        recipients = User.objects.filter(email__in=report.diffusion_recipients)
        for recipient in recipients:
            send_report_to_recipient(report, recipient)
            count += 1
        report.diffusion_last_run_at = now
        report.diffusion_next_run_at = compute_next_run_at(report.diffusion_frequency, after=now)
        report.save(update_fields=["diffusion_last_run_at", "diffusion_next_run_at"])
    return count
