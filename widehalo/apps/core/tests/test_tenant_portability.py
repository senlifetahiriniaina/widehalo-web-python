from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.services.documents import store_document
from apps.core.services.tenant_export import (
    FORMAT_VERSION,
    export_tenant_archive,
    import_tenant_archive,
)
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_export_then_import_round_trip_preserves_data() -> None:
    source = Tenant.objects.create(code="PORT-SRC", name="Portability Source")
    with use_tenant(source.id):
        store_document(
            tenant=source,
            uploaded_file=SimpleUploadedFile("one.txt", b"one", content_type="text/plain"),
        )
        store_document(
            tenant=source,
            uploaded_file=SimpleUploadedFile("two.txt", b"two", content_type="text/plain"),
        )

    archive_bytes = export_tenant_archive(source)

    target = Tenant.objects.create(code="PORT-DST", name="Portability Target")
    counts = import_tenant_archive(archive_bytes, target_tenant=target)

    with use_tenant(target.id):
        assert Document.objects.count() == 2
        assert set(Document.objects.values_list("original_name", flat=True)) == {
            "one.txt",
            "two.txt",
        }

    assert sum(counts.values()) == 2


def test_export_manifest_carries_a_format_version() -> None:
    import io
    import json
    import zipfile

    source = Tenant.objects.create(code="PORT-VER", name="Portability Version")
    archive_bytes = export_tenant_archive(source)
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(archive_bytes)).read("manifest.json"))

    assert manifest["format_version"] == FORMAT_VERSION


def test_import_of_a_future_unknown_format_version_is_rejected() -> None:
    import io
    import json
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format_version": 999, "models": []}))

    target = Tenant.objects.create(code="PORT-FUTURE", name="Portability Future")
    with pytest.raises(ValueError, match="Aucune migration"):
        import_tenant_archive(buffer.getvalue(), target_tenant=target)


@pytest.mark.slow
def test_reimport_of_a_representative_dataset_completes_within_30_minutes() -> None:
    """Objectif du cahier des charges : reimport verifie en moins de 30
    minutes. Marque `slow` — execute en nightly, pas a chaque run de CI
    standard, pour ne pas ralentir la boucle de developpement."""
    import time

    source = Tenant.objects.create(code="PORT-BIG", name="Portability Big")
    with use_tenant(source.id):
        for i in range(500):
            store_document(
                tenant=source,
                uploaded_file=SimpleUploadedFile(
                    f"doc-{i}.txt", f"contenu-{i}".encode(), content_type="text/plain"
                ),
            )

    started = time.monotonic()
    archive_bytes = export_tenant_archive(source)
    target = Tenant.objects.create(code="PORT-BIG-DST", name="Portability Big Target")
    import_tenant_archive(archive_bytes, target_tenant=target)
    elapsed = time.monotonic() - started

    assert elapsed < 1800

    with use_tenant(target.id):
        assert Document.objects.count() == 500
