"""Moteur generique `reporting.render(...)` (RPT-1/RPT-2) : dispatch
PDF/XLSX/CSV/JSON vers le renderer deja enregistre pour un code de rapport
donne (`core.services.reports_registry`) — n'implemente AUCUNE logique
metier de rapport lui-meme, seulement le pont params -> bytes.

RPT-6 (asynchronisme) : `generate_report()` cree systematiquement un
`RptJob`. Si `estimated_row_count` (fourni par l'appelant — ex. un
`queryset.count()` bon marche fait avant d'appeler ce module) laisse
presager un temps de generation superieur a `settings.REPORTING_ASYNC_
THRESHOLD_SECONDS`, la generation est deleguee a `core.tasks.enqueue()` et
la fonction retourne immediatement le job en etat `queued` ; sinon elle est
executee en synchrone dans le thread appelant et retourne le job deja
`done`.

**Simplification assumee, disclosed** (cf. plan §reporting, test
d'acceptance §5.11.7 n°4) : le CDC illustre RPT-6 avec un rapport de
50 000 lignes. Generer reellement 50 000 lignes en fixture de test serait
couteux et n'apporterait rien de plus que router un rapport minuscule via
EXACTEMENT le meme mecanisme — `ROWS_PER_SECOND_ESTIMATE` fixe un debit de
reference arbitraire mais raisonnable, et `estimated_row_count` reste un
parametre explicite fourni par l'appelant (jamais mesure automatiquement en
V1) : le test d'acceptance passe `estimated_row_count=50_000` avec un
`REPORTING_ASYNC_THRESHOLD_SECONDS` de test abaisse pour demontrer bout en
bout enqueue -> job `done` -> notification, sans jamais materialiser
50 000 lignes reelles."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.services.reports_registry import RegisteredReport, get_registered_report
from apps.reporting.models import RptDefinition, RptJob

logger = logging.getLogger(__name__)

# Debit de reference (lignes/seconde) utilise UNIQUEMENT pour estimer si un
# rapport doit partir en asynchrone — approximation grossiere assumee (pas
# de mesure reelle du materiel de production), documentee ci-dessus.
ROWS_PER_SECOND_ESTIMATE = 2000


class UnknownReportError(Exception):
    pass


class UnsupportedFormatError(Exception):
    pass


def rows_to_bytes(rows: list[dict[str, Any]], fields: tuple[str, ...], *, format: str) -> bytes:
    """Serialise une liste de lignes vers XLSX/CSV/JSON — meme logique que
    la fonction `rows_to_bytes` dupliquee dans chaque `services/reports.py`
    des 9 modules metier (duplication volontaire imposee par la regle de
    couplage n1 : ce module-ci n'est PAS importable par eux), utilisee ici
    par `reporting` pour ses PROPRES besoins de dispatch (le moteur ne
    remplace jamais les fonctions existantes, cf. docstring du module)."""
    resolved_fields = fields or (tuple(rows[0].keys()) if rows else ())

    if format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(resolved_fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in resolved_fields})
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(list(resolved_fields))
        for row in rows:
            sheet.append([row.get(field) for field in resolved_fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise UnsupportedFormatError(
        _("format de rapport non supporte : %(format)s") % {"format": format}
    )


def render_report(
    report: RegisteredReport, params: dict[str, Any], format: str, actor: User | None
) -> bytes:
    """Point d'entree synchrone pur (aucun effet de bord, aucune ecriture de
    `RptJob`) — reutilise par `legal_documents.render_and_archive` (REP4) en
    plus de `generate_report` ci-dessous."""
    if format == "pdf":
        if report.render_pdf is None:
            raise UnsupportedFormatError(
                _("le rapport %(code)s ne supporte pas le format PDF") % {"code": report.code}
            )
        return report.render_pdf(params, actor)

    if format in ("xlsx", "csv", "json"):
        if report.render_rows is None:
            raise UnsupportedFormatError(
                _("le rapport %(code)s ne supporte pas le format %(format)s")
                % {"code": report.code, "format": format}
            )
        rows = report.render_rows(params, actor)
        return rows_to_bytes(rows, report.fields, format=format)

    raise UnsupportedFormatError(
        _("format de rapport non supporte : %(format)s") % {"format": format}
    )


def _should_run_async(estimated_row_count: int | None) -> bool:
    if not estimated_row_count:
        return False
    estimated_seconds = estimated_row_count / ROWS_PER_SECOND_ESTIMATE
    return estimated_seconds > settings.REPORTING_ASYNC_THRESHOLD_SECONDS


def _run_job_sync(job_id: str) -> None:
    """Corps d'execution reel — appele directement en synchrone, ou via
    `core.tasks.enqueue()` en asynchrone (meme fonction dans les deux cas,
    cf. piege documente `core.events` : Django-Q2 serialise toujours ses
    arguments meme en mode `sync`, donc `job_id` en `str`, jamais l'objet)."""
    job = RptJob.objects.get(id=job_id)
    report = get_registered_report(job.report_code)
    if report is None:
        job.state = RptJob.STATE_FAILED
        job.error_message = _("rapport inconnu : %(code)s") % {"code": job.report_code}
        job.finished_at = timezone.now()
        job.save(update_fields=["state", "error_message", "finished_at"])
        return

    job.state = RptJob.STATE_RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["state", "started_at"])

    try:
        data = render_report(report, job.params, job.format, job.requested_by)
    except Exception as exc:  # noqa: BLE001 - job de fond, l'echec doit etre trace, pas propage
        job.state = RptJob.STATE_FAILED
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["state", "error_message", "finished_at"])

        # INT1 (chantier interactivite native inter-modules) : gap de
        # notification identifie par lecture directe — l'echec etait deja
        # trace sur `RptJob` mais SANS aucun evenement, contrairement au
        # succes (`reporting.job_done`, notification directe ci-dessous en
        # cas de reussite). `RptJob.state` (pas `status`, cf. verification
        # du modele reel) est le champ effectivement mute ci-dessus.
        if job.tenant_id:
            from apps.core.events import publish_event

            publish_event(
                "reporting.job_failed",
                {
                    "job_id": str(job.id),
                    "report_code": job.report_code,
                    "error_message": job.error_message,
                },
                tenant_id=str(job.tenant_id),
            )
        return

    job.file.save(f"{job.report_code}-{job.id}.{job.format}", ContentFile(data), save=False)
    job.state = RptJob.STATE_DONE
    job.finished_at = timezone.now()
    job.save(update_fields=["file", "state", "finished_at"])

    if job.tenant_id and job.requested_by is not None:
        from apps.core.services.notifications import dispatch_notification

        dispatch_notification(
            job.requested_by,
            "reporting.job_done",
            {"job_id": str(job.id), "report_code": job.report_code},
            tenant_id=str(job.tenant_id),
        )


def generate_report(
    *,
    code: str,
    params: dict[str, Any],
    format: str,
    lang: str,
    actor: User | None,
    tenant_id: str,
    estimated_row_count: int | None = None,
) -> RptJob:
    """RPT-1 : `reporting.render(code, params, format, lang, actor)` du
    cadrage — nomme `generate_report` ici pour eviter la collision avec le
    mot reserve `format`/le nom `render` deja tres charge dans Django. Cree
    systematiquement un `RptJob`, l'execute en synchrone ou le route vers
    `core.tasks.enqueue()` selon `_should_run_async` (RPT-6)."""
    report = get_registered_report(code)
    if report is None:
        raise UnknownReportError(_("rapport inconnu : %(code)s") % {"code": code})

    definition = RptDefinition.objects.filter(tenant_id=tenant_id, code=code).first()
    if definition is not None and not definition.is_enabled:
        raise UnknownReportError(_("rapport désactivé pour ce tenant : %(code)s") % {"code": code})

    job = RptJob.objects.create(
        tenant_id=tenant_id,
        report_code=code,
        params=params,
        format=format,
        lang=lang,
        requested_by=actor,
        expires_at=timezone.now() + settings.REPORTING_JOB_RETENTION,
    )

    if _should_run_async(estimated_row_count):
        from apps.core.tasks import enqueue

        enqueue(_run_job_sync, str(job.id), task_name=f"reporting-job-{job.id}")
    else:
        _run_job_sync(str(job.id))
        job.refresh_from_db()

    return job


def purge_expired_jobs() -> int:
    """RPT-6 : purge des fichiers de job a 7 jours — meme patron que
    `core.services.sandbox.purge_expired_sandboxes` (la RLS Postgres
    s'applique aussi a `all_objects`, seul le filtrage cote Django en est
    exempte : on ne peut donc pas selectionner globalement les jobs expires
    tous tenants confondus, il faut boucler tenant par tenant sous
    `activate_tenant`, comme le fait deja `sandbox.py`)."""
    from apps.core.models.tenant import Tenant
    from apps.core.tenant_context import activate_tenant

    now = timezone.now()
    count = 0
    for tenant_id in Tenant.objects.values_list("id", flat=True):
        try:
            with activate_tenant(tenant_id):
                expired = RptJob.objects.filter(expires_at__lte=now)
                count += expired.count()
                for job in expired:
                    job.file.delete(save=False)
                expired.delete()
        except Exception:  # noqa: BLE001 — L0-2 : un tenant en echec ne prive plus les suivants de leur traitement. L'exception est journalisee puis absorbee — meme decision que `apps.core.services.scheduled_commands.tenant_step`, applique ici au niveau du service parce que c'est lui, et non la commande, qui porte la boucle.
            logger.exception("Purge des rapports en echec pour le tenant %s", tenant_id)
    return count
