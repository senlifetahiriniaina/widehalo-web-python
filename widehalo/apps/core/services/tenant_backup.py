"""Sauvegarde/restauration en libre-service d'un tenant (BKP2-3) : reutilise
`apps.core.services.tenant_export` (export/import deja durci, testes) et
`apps.core.services.documents.store_document` (stockage generique deja
dedupliqu par SHA-256 — aucun nouveau mecanisme de stockage, decision
actee avec l'utilisateur). Chaque appel journalise un
`core.TenantDataOperation`, y compris en cas d'echec (jamais un echec
silencieusement perdu)."""

from __future__ import annotations

import json
import logging
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models.backup import TenantBackupSchedule, TenantDataOperation
from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.core.services.tenant_export import export_tenant_archive, import_tenant_archive
from apps.core.services.tenant_reset import reset_tenant_data

logger = logging.getLogger(__name__)


def confirm_tenant_code(tenant: Tenant, confirmation: str) -> bool:
    """Revalidation stricte, cote SERVEUR, de la saisie « tapez le code du
    tenant pour confirmer » exigee avant restauration/reinitialisation
    (operations irreversibles sans sauvegarde prealable, cf. plan) — une
    verification uniquement cote client (JS) ne suffit jamais pour une
    action destructrice de ce niveau. Compare au `code` (identifiant
    stable, unique, jamais accentue) plutot qu'au `name` (raison sociale
    libre, peut contenir accents/espaces/homonymes)."""
    return confirmation.strip() == tenant.code


def _archive_summary(archive_bytes: bytes) -> dict[str, int]:
    """Resume grossier (nombre de lignes par modele exporte), lu directement
    depuis l'archive plutot que reconstruit ailleurs — evite de reparser
    redondamment le manifeste, cf. `tenant_export.export_tenant_archive`
    (meme format `manifest.json` + `data/<label>.json`)."""
    archive = zipfile.ZipFile(BytesIO(archive_bytes))
    manifest = json.loads(archive.read("manifest.json"))
    summary: dict[str, int] = {}
    for label in manifest["models"]:
        rows = json.loads(archive.read(f"data/{label}.json"))
        summary[label] = len(rows)
    return summary


def _prune_backup_retention(tenant: Tenant) -> None:
    """Purge les `TenantDataOperation(operation_type="backup")` les plus
    anciennes au-dela de `TenantBackupSchedule.retention_count`, si une
    planification existe pour ce tenant et fixe une retention (`None` ==
    conserver toutes les sauvegardes). Dereference le `Document` associe a
    chaque operation purgee (decremente `reference_count`, supprime le
    fichier physique s'il atteint zero) plutot que de laisser un
    `Document` orphelin — aucun helper de decrement n'existait avant ce
    chantier, cf. rapport de fin de chantier."""
    schedule = TenantBackupSchedule.all_objects.filter(tenant=tenant).first()
    if schedule is None or schedule.retention_count is None:
        return

    backups = list(
        TenantDataOperation.all_objects.filter(
            tenant=tenant, operation_type=TenantDataOperation.TYPE_BACKUP
        ).order_by("-created_at")
    )
    excess = backups[schedule.retention_count :]
    for operation in excess:
        document = operation.document
        operation.delete()
        if document is not None:
            release_document_reference(document)


def release_document_reference(document: Document) -> None:
    """Decremente `Document.reference_count`, supprime l'enregistrement (et
    le fichier physique) s'il atteint zero. Petit gap comble par ce
    chantier : `store_document` incremente deja `reference_count` a chaque
    dedup, mais aucun appelant existant n'avait jamais eu besoin de
    dereferencer un `Document` avant la purge de retention introduite ici
    — sans ce decrement, chaque sauvegarde purgee laisserait un fichier
    orphelin en stockage."""
    document.reference_count -= 1
    if document.reference_count <= 0:
        document.file.delete(save=False)
        document.delete()
    else:
        document.save(update_fields=["reference_count"])


def create_tenant_backup(
    tenant: Tenant,
    *,
    trigger: str = TenantDataOperation.TRIGGER_MANUAL,
    triggered_by: User | None = None,
) -> TenantDataOperation:
    """Exporte l'integralite des donnees du tenant et les stocke via
    `core.Document` (dedup SHA-256 deja existant — deux sauvegardes
    consecutives sans changement de donnees reutilisent le meme
    `Document`, comportement beneficique assume, pas un bug)."""
    try:
        archive_bytes = export_tenant_archive(tenant)
        uploaded_file = SimpleUploadedFile(
            name=f"{tenant.code}-{timezone.now():%Y%m%d%H%M%S}.zip",
            content=archive_bytes,
            content_type="application/zip",
        )
        document = store_document(
            tenant=tenant,
            uploaded_file=uploaded_file,
            uploaded_by=triggered_by,
            content_object=tenant,
        )
    except Exception as exc:  # noqa: BLE001 — journalisation systematique, jamais un echec perdu
        TenantDataOperation.objects.create(
            tenant=tenant,
            operation_type=TenantDataOperation.TYPE_BACKUP,
            status=TenantDataOperation.STATUS_FAILED,
            trigger=trigger,
            error_message=str(exc),
            triggered_by=triggered_by,
        )
        raise

    operation = TenantDataOperation.objects.create(
        tenant=tenant,
        operation_type=TenantDataOperation.TYPE_BACKUP,
        status=TenantDataOperation.STATUS_SUCCESS,
        trigger=trigger,
        document=document,
        summary=_archive_summary(archive_bytes),
        triggered_by=triggered_by,
    )
    _prune_backup_retention(tenant)
    return operation


def restore_tenant_from_archive(
    tenant: Tenant,
    archive_bytes: bytes,
    *,
    source_document: Document | None = None,
    triggered_by: User | None = None,
) -> TenantDataOperation:
    """Ecrase le tenant courant : vide ses donnees (`reseed=False`, la
    reimportation qui suit apporte deja de vraies donnees) puis reimporte
    l'archive dedans (`import_tenant_archive` supporte deja un tenant
    cible arbitraire, regenere des UUID7 pour chaque ligne importee) —
    conformement a la decision actee (restauration = ecrasement du tenant
    courant, jamais la creation d'un nouveau tenant)."""
    try:
        reset_tenant_data(tenant, reseed=False)
        counts = import_tenant_archive(archive_bytes, target_tenant=tenant)
    except Exception as exc:  # noqa: BLE001 — journalisation systematique, jamais un echec perdu
        TenantDataOperation.objects.create(
            tenant=tenant,
            operation_type=TenantDataOperation.TYPE_RESTORE,
            status=TenantDataOperation.STATUS_FAILED,
            trigger=TenantDataOperation.TRIGGER_MANUAL,
            document=source_document,
            error_message=str(exc),
            triggered_by=triggered_by,
        )
        raise

    return TenantDataOperation.objects.create(
        tenant=tenant,
        operation_type=TenantDataOperation.TYPE_RESTORE,
        status=TenantDataOperation.STATUS_SUCCESS,
        trigger=TenantDataOperation.TRIGGER_MANUAL,
        document=source_document,
        summary=counts,
        triggered_by=triggered_by,
    )


def run_due_tenant_backups() -> list[TenantDataOperation]:
    """Boucle les planifications actives echues, declenche une sauvegarde
    pour chacune, avance `next_run_at` selon `frequency`. Invoquee par la
    commande `manage.py run_tenant_backups`, elle-meme SANS cron
    auto-enregistre (decision actee — c'est a l'operateur cron systeme/
    Docker de l'invoquer periodiquement, meme convention que tous les jobs
    planifies deja existants de ce depot).

    **Boucle `Tenant.objects.all()` + `activate_tenant` par tenant**
    (jamais un `TenantBackupSchedule.all_objects.filter(...)` global) —
    `Tenant` n'est pas lui-meme tenant-scope (pas de RLS dessus), mais
    `TenantBackupSchedule` L'EST : la policy RLS Postgres
    (`tenant_id = current_setting('app.tenant_id')`) s'applique a TOUTE
    requete, y compris via `all_objects` (qui ne contourne que le
    filtrage cote Django, jamais la RLS **base de donnees**, cf.
    docstring de `apps.core.management.commands.apply_rls`) — une requete
    inter-tenant sur cette table ne verrait donc, au mieux, que les lignes
    du DERNIER tenant active (au pire, rien du tout hors de tout
    contexte). Meme discipline que tous les jobs planifies soeurs
    (`run_sales_recurrences`...) : boucle les tenants un par un, active
    le contexte AVANT toute lecture de leurs donnees."""
    from dateutil.relativedelta import relativedelta

    from apps.core.tenant_context import activate_tenant

    step_by_frequency = {
        TenantBackupSchedule.FREQUENCY_DAILY: relativedelta(days=1),
        TenantBackupSchedule.FREQUENCY_WEEKLY: relativedelta(weeks=1),
        TenantBackupSchedule.FREQUENCY_MONTHLY: relativedelta(months=1),
    }

    now = timezone.now()
    operations: list[TenantDataOperation] = []
    for tenant in Tenant.objects.all():
        # L0-2 : une sauvegarde en echec ne prive plus les tenants suivants de
        # la leur. C'est le cas ou l'isolation compte le plus : une nuit sans
        # sauvegarde passe inapercue jusqu'au jour ou l'on en a besoin.
        try:
            with activate_tenant(tenant.id):
                schedule = TenantBackupSchedule.objects.filter(
                    is_active=True, next_run_at__lte=now
                ).first()
                if schedule is None:
                    continue
                operation = create_tenant_backup(
                    tenant, trigger=TenantDataOperation.TRIGGER_SCHEDULED
                )
                operations.append(operation)
                schedule.last_run_at = now
                schedule.next_run_at = now + step_by_frequency[schedule.frequency]
                schedule.save(update_fields=["last_run_at", "next_run_at"])
        except Exception:  # noqa: BLE001 — un tenant en echec ne bloque jamais les suivants
            logger.exception("Sauvegarde planifiee en echec pour le tenant %s", tenant.code)

    return operations
