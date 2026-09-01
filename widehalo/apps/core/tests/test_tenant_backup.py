"""Tests de `apps.core.services.tenant_backup` (BKP2) : sauvegarde cree un
Document+journal, dedup des sauvegardes inchangees, restauration
round-trip (ecrase le tenant courant, jamais un nouveau tenant)."""

from __future__ import annotations

import pytest

from apps.core.models.backup import TenantDataOperation
from apps.core.models.document import Document
from apps.core.models.risk import CATEGORY_OTHER, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.tenant_backup import create_tenant_backup, restore_tenant_from_archive
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _create_owner(email: str) -> User:
    return User.objects.create_user(email=email, password="Str0ngPassw0rd!23")


def test_manual_backup_creates_one_document_and_one_operation() -> None:
    tenant = Tenant.objects.create(code="BKP-ONE", name="Backup One")
    owner = _create_owner("owner1@backup.test")
    with use_tenant(tenant.id):
        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=1, impact=1, score=1, owner=owner
        )

    operation = create_tenant_backup(tenant, triggered_by=owner)

    assert operation.operation_type == TenantDataOperation.TYPE_BACKUP
    assert operation.status == TenantDataOperation.STATUS_SUCCESS
    assert operation.document is not None
    assert TenantDataOperation.all_objects.filter(tenant=tenant).count() == 1
    assert Document.all_objects.filter(tenant=tenant).count() == 1
    assert sum(operation.summary.values()) == 1


def test_two_consecutive_backups_of_unchanged_tenant_reuse_the_same_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedup reelle par SHA-256 (`store_document`) : deux sauvegardes dont
    l'archive exportee est rigoureusement identique reutilisent le meme
    `Document` (`reference_count` incremente, pas un second fichier).

    Octets d'export figes via monkeypatch plutot que via deux appels reels
    a `export_tenant_archive` : EN PRATIQUE, chaque sauvegarde ajoute au
    tenant un nouveau `Document`+`TenantDataOperation` que la sauvegarde
    SUIVANTE capture a son tour (export integral et fidele, y compris de
    l'historique des sauvegardes elles-memes, cf. docstring de
    `tenant_export.export_tenant_archive` — comportement intentionnel,
    jamais modifie par ce chantier) : au-dela de la toute premiere
    sauvegarde, deux exports reels ne sont donc plus jamais des octets
    identiques. Ce test isole donc le mecanisme de dedup lui-meme (deja
    correctement cable par `create_tenant_backup` vers `store_document`)
    plutot que de pretendre a une byte-identite qui ne se produit plus une
    fois un historique de sauvegardes constitue — limite assumee et
    disclosed explicitement, cf. rapport de fin de chantier."""
    import apps.core.services.tenant_backup as tenant_backup_module

    tenant = Tenant.objects.create(code="BKP-DEDUP", name="Backup Dedup")
    owner = _create_owner("owner2@backup.test")
    with use_tenant(tenant.id):
        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=2, impact=2, score=4, owner=owner
        )

    import io
    import json
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"format_version": 1, "exported_at": "2026-01-01", "models": []}),
        )
    frozen_archive_bytes = buffer.getvalue()
    monkeypatch.setattr(
        tenant_backup_module, "export_tenant_archive", lambda _tenant: frozen_archive_bytes
    )

    with use_tenant(tenant.id):
        first = create_tenant_backup(tenant, triggered_by=owner)
        second = create_tenant_backup(tenant, triggered_by=owner)

    assert first.document_id == second.document_id
    document = Document.all_objects.get(id=first.document_id)
    assert document.reference_count == 2
    assert Document.all_objects.filter(tenant=tenant).count() == 1
    assert TenantDataOperation.all_objects.filter(tenant=tenant).count() == 2


def test_restore_round_trip_overwrites_current_tenant_state() -> None:
    tenant = Tenant.objects.create(code="BKP-RESTORE", name="Backup Restore", country_code="MG")
    owner = _create_owner("owner3@backup.test")
    with use_tenant(tenant.id):
        original = RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=3, impact=3, score=9, owner=owner
        )
        original_id = original.id

    backup_operation = create_tenant_backup(tenant, triggered_by=owner)
    archive_bytes = backup_operation.document.file.read()
    backup_operation.document.file.seek(0)

    with use_tenant(tenant.id):
        RiskItem.objects.filter(tenant=tenant).delete()
        RiskItem.objects.create(
            tenant=tenant, category=CATEGORY_OTHER, likelihood=5, impact=5, score=25, owner=owner
        )
    assert RiskItem.all_objects.filter(tenant=tenant).count() == 1
    assert not RiskItem.all_objects.filter(id=original_id).exists()

    restore_operation = restore_tenant_from_archive(
        tenant, archive_bytes, source_document=backup_operation.document, triggered_by=owner
    )

    assert restore_operation.operation_type == TenantDataOperation.TYPE_RESTORE
    assert restore_operation.status == TenantDataOperation.STATUS_SUCCESS
    with use_tenant(tenant.id):
        restored_items = list(RiskItem.objects.all())
    assert len(restored_items) == 1
    assert restored_items[0].likelihood == 3
    assert restored_items[0].score == 9
    # L'id d'origine ne survit jamais a un import (nouvel UUID7 genere, cf.
    # docstring de `import_tenant_archive`).
    assert restored_items[0].id != original_id
