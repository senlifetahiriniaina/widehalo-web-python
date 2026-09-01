"""API des sauvegardes/restaurations/reinitialisations en libre-service
d'un tenant (BKP4) : garde par `is_superuser` STRICT sur TOUS les
endpoints (`require_superuser`, cf. `apps.core.services.permissions`) —
JAMAIS une permission RBAC/`admin`/`direction` (correction actee apres le
demarrage de ce chantier par le commanditaire : ces actions depassent la
portee du pilotage transverse habituel de ces roles — cf. rapport de fin
de chantier et `apps.core.models.backup.TenantDataOperation`).
Restauration et reinitialisation sont irreversibles sans sauvegarde
prealable.

**Confirmation stricte revalidee cote serveur** (jamais uniquement cote
client) : `restore_endpoint`/`reset_endpoint` exigent un champ `confirm`
egal au `code` exact du tenant courant (`confirm_tenant_code`), sans quoi
la requete est refusee en 400 — meme via un appel API direct qui
contournerait tout JS cote ecran."""

from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import File, Form, Router, Schema
from ninja.files import UploadedFile

from apps.core.models.backup import TenantBackupSchedule, TenantDataOperation
from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_superuser
from apps.core.services.tenant_backup import (
    confirm_tenant_code,
    create_tenant_backup,
    restore_tenant_from_archive,
)
from apps.core.services.tenant_reset import reset_tenant_data

router = Router(tags=["tenant-backup"])


def _current_tenant(request) -> Tenant:
    return get_object_or_404(Tenant, id=request.headers.get("X-Tenant-Id"))


def _serialize_operation(operation: TenantDataOperation) -> dict:
    return {
        "id": str(operation.id),
        "operation_type": operation.operation_type,
        "status": operation.status,
        "trigger": operation.trigger,
        "document_id": str(operation.document_id) if operation.document_id else None,
        "summary": operation.summary,
        "error_message": operation.error_message,
        "created_at": operation.created_at.isoformat(),
    }


def _serialize_schedule(schedule: TenantBackupSchedule) -> dict:
    return {
        "id": str(schedule.id),
        "frequency": schedule.frequency,
        "retention_count": schedule.retention_count,
        "is_active": schedule.is_active,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
    }


@router.get("/backups")
@require_superuser
def list_backups(request):
    tenant = _current_tenant(request)
    operations = TenantDataOperation.objects.filter(tenant=tenant).order_by("-created_at")
    return {"results": [_serialize_operation(o) for o in operations]}


@router.post("/backups")
@require_superuser
def create_backup_endpoint(request):
    tenant = _current_tenant(request)
    operation = create_tenant_backup(
        tenant, trigger=TenantDataOperation.TRIGGER_MANUAL, triggered_by=request.auth
    )
    return _serialize_operation(operation)


class ResetIn(Schema):
    confirm: str


@router.post("/backups/restore")
@require_superuser
def restore_endpoint(
    request,
    confirm: str = Form(...),  # noqa: B008 — idiome django-ninja standard
    document_id: str = Form(""),  # noqa: B008 — idiome django-ninja standard
    file: UploadedFile = File(None),  # noqa: B008 — idiome django-ninja standard
):
    """Restaure depuis, au choix : une archive DEJA stockee
    (`document_id`, ex. une sauvegarde precedente de la liste) OU une
    archive EXTERNE uploadee (`file`) — meme idiome multipart
    `ninja.File`/`ninja.Form` que `apps.chat.api.create_message`.
    Exactement l'un des deux doit etre fourni."""
    tenant = _current_tenant(request)
    if not confirm_tenant_code(tenant, confirm):
        return JsonResponse(
            {"detail": _("Le code saisi ne correspond pas au code exact de cette société.")},
            status=400,
        )

    if bool(document_id) == bool(file):
        return JsonResponse(
            {
                "detail": _(
                    "Fournissez soit l'identifiant d'une sauvegarde existante, "
                    "soit un fichier d'archive — jamais les deux, ni aucun des deux."
                )
            },
            status=400,
        )

    if document_id:
        source_document = get_object_or_404(Document, id=document_id, tenant=tenant)
        source_document.file.open("rb")
        archive_bytes = source_document.file.read()
        source_document.file.close()
    else:
        source_document = None
        archive_bytes = file.read()

    operation = restore_tenant_from_archive(
        tenant, archive_bytes, source_document=source_document, triggered_by=request.auth
    )
    return _serialize_operation(operation)


@router.post("/reset")
@require_superuser
def reset_endpoint(request, payload: ResetIn):
    tenant = _current_tenant(request)
    if not confirm_tenant_code(tenant, payload.confirm):
        return JsonResponse(
            {"detail": _("Le code saisi ne correspond pas au code exact de cette société.")},
            status=400,
        )

    try:
        summary = reset_tenant_data(tenant, reseed=True, triggered_by=request.auth)
    except Exception as exc:  # noqa: BLE001 — journalisation systematique, jamais un echec perdu
        TenantDataOperation.objects.create(
            tenant=tenant,
            operation_type=TenantDataOperation.TYPE_RESET,
            status=TenantDataOperation.STATUS_FAILED,
            trigger=TenantDataOperation.TRIGGER_MANUAL,
            error_message=str(exc),
            triggered_by=request.auth,
        )
        raise

    operation = TenantDataOperation.objects.create(
        tenant=tenant,
        operation_type=TenantDataOperation.TYPE_RESET,
        status=TenantDataOperation.STATUS_SUCCESS,
        trigger=TenantDataOperation.TRIGGER_MANUAL,
        summary=summary,
        triggered_by=request.auth,
    )
    return _serialize_operation(operation)


class BackupScheduleIn(Schema):
    frequency: str = TenantBackupSchedule.FREQUENCY_DAILY
    retention_count: int | None = None
    is_active: bool = True


@router.get("/backup-schedule")
@require_superuser
def get_backup_schedule(request):
    tenant = _current_tenant(request)
    schedule, _created = TenantBackupSchedule.objects.get_or_create(tenant=tenant)
    return _serialize_schedule(schedule)


@router.put("/backup-schedule")
@require_superuser
def update_backup_schedule(request, payload: BackupScheduleIn):
    tenant = _current_tenant(request)
    schedule, _created = TenantBackupSchedule.objects.get_or_create(tenant=tenant)
    schedule.frequency = payload.frequency
    schedule.retention_count = payload.retention_count
    schedule.is_active = payload.is_active
    schedule.save(update_fields=["frequency", "retention_count", "is_active"])
    return _serialize_schedule(schedule)
