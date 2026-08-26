from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.services.sandbox import clone_tenant_to_sandbox, purge_expired_sandboxes
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_clone_tenant_to_sandbox_creates_a_distinct_anonymized_tenant() -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.core.services.documents import store_document

    source = Tenant.objects.create(code="SBX-SRC", name="Source Tenant")
    with use_tenant(source.id):
        store_document(
            tenant=source,
            uploaded_file=SimpleUploadedFile("f.txt", b"data", content_type="text/plain"),
        )

    sandbox = clone_tenant_to_sandbox(source)

    assert sandbox.id != source.id
    assert sandbox.is_sandbox is True
    assert sandbox.sandbox_source_id == source.id
    assert sandbox.sandbox_expires_at is not None

    with use_tenant(sandbox.id):
        cloned_docs = Document.objects.all()
        assert cloned_docs.count() == 1
        assert cloned_docs.first().original_name != "f.txt"  # anonymise

    # Le tenant source n'est pas affecte par le clonage.
    with use_tenant(source.id):
        assert Document.objects.count() == 1


def test_purge_expired_sandboxes_removes_only_expired_ones() -> None:
    source = Tenant.objects.create(code="SBX-SRC2", name="Source Tenant 2")
    expired_sandbox = clone_tenant_to_sandbox(source, expires_in_days=30)
    Tenant.objects.filter(pk=expired_sandbox.pk).update(
        sandbox_expires_at=timezone.now() - timedelta(days=1)
    )
    fresh_sandbox = clone_tenant_to_sandbox(source, expires_in_days=30)

    purged_count = purge_expired_sandboxes()

    assert purged_count == 1
    assert not Tenant.objects.filter(pk=expired_sandbox.pk).exists()
    assert Tenant.objects.filter(pk=fresh_sandbox.pk).exists()
