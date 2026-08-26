from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.services.documents import store_document
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_uploading_the_same_file_twice_stores_only_one_copy() -> None:
    tenant = Tenant.objects.create(code="DOC-T", name="Doc Tenant")

    with use_tenant(tenant.id):
        file1 = SimpleUploadedFile("a.txt", b"hello world", content_type="text/plain")
        file2 = SimpleUploadedFile("a-copy.txt", b"hello world", content_type="text/plain")

        doc1 = store_document(tenant=tenant, uploaded_file=file1)
        doc2 = store_document(tenant=tenant, uploaded_file=file2)

        assert doc1.id == doc2.id
        assert Document.objects.count() == 1
        doc1.refresh_from_db()
        assert doc1.reference_count == 2


def test_uploaded_file_is_scanned_and_marked_clean_by_default() -> None:
    tenant = Tenant.objects.create(code="DOC-T2", name="Doc Tenant 2")

    with use_tenant(tenant.id):
        file = SimpleUploadedFile("b.txt", b"some content", content_type="text/plain")
        doc = store_document(tenant=tenant, uploaded_file=file)
        assert doc.av_scan_status == Document.SCAN_CLEAN


def test_different_files_are_stored_separately() -> None:
    tenant = Tenant.objects.create(code="DOC-T3", name="Doc Tenant 3")

    with use_tenant(tenant.id):
        file1 = SimpleUploadedFile("c.txt", b"content one", content_type="text/plain")
        file2 = SimpleUploadedFile("d.txt", b"content two", content_type="text/plain")
        store_document(tenant=tenant, uploaded_file=file1)
        store_document(tenant=tenant, uploaded_file=file2)

        assert Document.objects.count() == 2
