"""Ecrans de sauvegarde/restauration/reinitialisation en libre-service
d'un tenant (BKP5) : gardes par `is_superuser` STRICT, jamais un role
`admin`/`direction` — memes idiome/discipline que `settings_page`
(`apps.core.views.pages`) pour le garde, et que `apps.core.views.
admin_users` pour le reste (aucun `forms.py` dans ce depot, formulaires
HTML bruts geres a la main, aucun `django.contrib.messages`).

**Confirmation stricte** (restauration/reinitialisation, irreversibles
sans sauvegarde prealable) : un champ texte « tapez le code du tenant »
est REVALIDE cote serveur (`confirm_tenant_code`) avant tout appel aux
services — jamais une garantie uniquement cote client."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.models.backup import TenantBackupSchedule, TenantDataOperation
from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.tenant_backup import (
    confirm_tenant_code,
    create_tenant_backup,
    restore_tenant_from_archive,
)
from apps.core.services.tenant_reset import reset_tenant_data
from apps.core.views.smart_table import DEFAULT_PAGE_SIZE
from apps.core.views.tenant_web import resolve_tenant


def _forbidden_unless_superuser(request: HttpRequest) -> HttpResponse | None:
    if not request.user.is_superuser:
        return HttpResponse(status=403)
    return None


@login_required
def backup_list(request: HttpRequest) -> HttpResponse:
    denied = _forbidden_unless_superuser(request)
    if denied is not None:
        return denied

    tenant = resolve_tenant(request)
    errors: list[str] = []

    if request.method == "POST" and request.POST.get("action") == "backup_now":
        create_tenant_backup(
            tenant,
            trigger=TenantDataOperation.TRIGGER_MANUAL,
            triggered_by=cast(User, request.user),
        )
        return redirect("backup_list")

    if request.method == "POST" and request.POST.get("action") == "restore":
        confirm = request.POST.get("confirm", "")
        document_id = request.POST.get("document_id", "")
        uploaded_file: UploadedFile | None = request.FILES.get("file")

        if not confirm_tenant_code(tenant, confirm):
            errors.append(_("Le code saisi ne correspond pas au code exact de cette société."))
        elif bool(document_id) == bool(uploaded_file):
            errors.append(
                _(
                    "Choisissez soit une sauvegarde existante, soit un fichier "
                    "d'archive — jamais les deux, ni aucun des deux."
                )
            )
        else:
            if document_id:
                source_document = get_object_or_404(Document, id=document_id, tenant=tenant)
                source_document.file.open("rb")
                archive_bytes = source_document.file.read()
                source_document.file.close()
            else:
                source_document = None
                assert uploaded_file is not None
                archive_bytes = uploaded_file.read()

            restore_tenant_from_archive(
                tenant,
                archive_bytes,
                source_document=source_document,
                triggered_by=cast(User, request.user),
            )
            return redirect("backup_list")

    all_operations = TenantDataOperation.objects.filter(tenant=tenant).order_by("-created_at")
    paginator = Paginator(all_operations, DEFAULT_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Le <select> de restauration doit toujours pouvoir proposer N'IMPORTE
    # QUELLE sauvegarde reussie, pas seulement celles de la page affichee —
    # requete separee, volontairement non paginee (cf. plan « page de liste
    # complete des sauvegardes »).
    restorable_backups = TenantDataOperation.objects.filter(
        tenant=tenant,
        operation_type=TenantDataOperation.TYPE_BACKUP,
        status=TenantDataOperation.STATUS_SUCCESS,
        document__isnull=False,
    ).order_by("-created_at")

    return render(
        request,
        "backup_list.html",
        {
            "tenant": tenant,
            "operations": page_obj,
            "restorable_backups": restorable_backups,
            "errors": errors,
        },
    )


@login_required
def backup_download(request: HttpRequest, document_id: str) -> HttpResponse:
    denied = _forbidden_unless_superuser(request)
    if denied is not None:
        return denied

    tenant = resolve_tenant(request)
    document = get_object_or_404(Document, id=document_id, tenant=tenant)
    document.file.open("rb")
    data = document.file.read()
    document.file.close()
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{document.original_name}"'
    return response


@login_required
def backup_schedule_view(request: HttpRequest) -> HttpResponse:
    denied = _forbidden_unless_superuser(request)
    if denied is not None:
        return denied

    tenant = resolve_tenant(request)
    schedule, _created = TenantBackupSchedule.objects.get_or_create(tenant=tenant)
    errors: list[str] = []

    if request.method == "POST":
        frequency = request.POST.get("frequency", "")
        valid_frequencies = {code for code, _label in TenantBackupSchedule.FREQUENCY_CHOICES}
        if frequency not in valid_frequencies:
            errors.append(_("Fréquence invalide."))
        else:
            retention_raw = request.POST.get("retention_count", "").strip()
            retention_count = int(retention_raw) if retention_raw else None
            schedule.frequency = frequency
            schedule.retention_count = retention_count
            schedule.is_active = request.POST.get("is_active") == "on"
            schedule.save(update_fields=["frequency", "retention_count", "is_active"])
            return redirect("backup_schedule")

    return render(
        request, "backup_schedule.html", {"tenant": tenant, "schedule": schedule, "errors": errors}
    )


@login_required
def reset_company_data(request: HttpRequest) -> HttpResponse:
    denied = _forbidden_unless_superuser(request)
    if denied is not None:
        return denied

    tenant = resolve_tenant(request)
    errors: list[str] = []

    if request.method == "POST":
        confirm = request.POST.get("confirm", "")
        if not confirm_tenant_code(tenant, confirm):
            errors.append(_("Le code saisi ne correspond pas au code exact de cette société."))
        else:
            try:
                summary = reset_tenant_data(
                    tenant, reseed=True, triggered_by=cast(User, request.user)
                )
            except Exception as exc:  # noqa: BLE001 — journalisation systematique
                TenantDataOperation.objects.create(
                    tenant=tenant,
                    operation_type=TenantDataOperation.TYPE_RESET,
                    status=TenantDataOperation.STATUS_FAILED,
                    trigger=TenantDataOperation.TRIGGER_MANUAL,
                    error_message=str(exc),
                    triggered_by=cast(User, request.user),
                )
                raise
            TenantDataOperation.objects.create(
                tenant=tenant,
                operation_type=TenantDataOperation.TYPE_RESET,
                status=TenantDataOperation.STATUS_SUCCESS,
                trigger=TenantDataOperation.TRIGGER_MANUAL,
                summary=summary,
                triggered_by=cast(User, request.user),
            )
            return redirect("backup_list")

    return render(request, "reset_company_data.html", {"tenant": tenant, "errors": errors})
