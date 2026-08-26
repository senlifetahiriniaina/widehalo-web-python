from __future__ import annotations

import hashlib
from typing import IO, Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile

from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.antivirus import get_scanner


def _sha256_of(file: IO[bytes]) -> str:
    file.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: file.read(65536), b""):
        digest.update(chunk)
    file.seek(0)
    return digest.hexdigest()


def store_document(
    *,
    tenant: Tenant,
    uploaded_file: UploadedFile[Any],
    uploaded_by: User | None = None,
    content_object: Any = None,
) -> Document:
    """Deduplique par SHA-256 (un meme fichier envoye deux fois par le
    meme tenant ne stocke qu'une copie physique — incremente
    `reference_count`). L'antivirus est toujours consulte, quelle que
    soit l'implementation active (cf. services/antivirus.py)."""
    sha256 = _sha256_of(uploaded_file)

    existing = Document.objects.filter(tenant=tenant, sha256=sha256).first()
    if existing:
        existing.reference_count += 1
        existing.save(update_fields=["reference_count"])
        return existing

    scan_result = get_scanner().scan(uploaded_file)
    uploaded_file.seek(0)

    document = Document.objects.create(
        tenant=tenant,
        created_by=uploaded_by,
        content_type=(
            None
            if content_object is None
            else ContentType.objects.get_for_model(content_object.__class__)
        ),
        object_id="" if content_object is None else str(content_object.pk),
        file=ContentFile(uploaded_file.read(), name=uploaded_file.name or "fichier"),
        original_name=uploaded_file.name or "fichier",
        mime_type=uploaded_file.content_type or "",
        size=uploaded_file.size or 0,
        sha256=sha256,
        av_scan_status=scan_result.status,
    )
    return document
