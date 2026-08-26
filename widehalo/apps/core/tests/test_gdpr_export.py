from __future__ import annotations

import io
import zipfile

import pytest

from apps.core.models.user import User
from apps.core.services.gdpr import anonymize_user, export_personal_data_zip

pytestmark = pytest.mark.django_db


def test_export_personal_data_produces_a_valid_zip_with_core_data() -> None:
    user = User.objects.create_user(
        email="gdpr@example.com", password="Str0ngPassw0rd!23", first_name="Jean"
    )

    archive_bytes = export_personal_data_zip(user)
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes))

    assert archive.testzip() is None
    assert "core.json" in archive.namelist()

    import json

    core_data = json.loads(archive.read("core.json"))
    assert core_data["email"] == "gdpr@example.com"
    assert core_data["first_name"] == "Jean"


def test_anonymize_user_scrubs_personal_data_but_keeps_the_id() -> None:
    user = User.objects.create_user(
        email="toanonymize@example.com", password="Str0ngPassw0rd!23", first_name="Marie"
    )
    original_id = user.id

    anonymize_user(user)
    user.refresh_from_db()

    assert user.id == original_id
    assert user.email != "toanonymize@example.com"
    assert user.first_name != "Marie"
    assert user.is_active is False
    assert not user.has_usable_password()
