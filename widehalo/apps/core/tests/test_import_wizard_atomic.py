from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.services.import_wizard import commit_import, dry_run_validate, parse_mapping

pytestmark = pytest.mark.django_db


def test_parse_mapping_associates_columns_to_fields() -> None:
    header = ["Code", "Nom", "Ignoré"]
    mapping = {"Code": "code", "Nom": "name"}
    index_to_field = parse_mapping(header, mapping)
    assert index_to_field == {0: "code", 1: "name"}


def test_dry_run_validates_rows_without_writing_to_db() -> None:
    index_to_field = {0: "code", 1: "name"}
    rows = [["IMP-1", "Import One"], ["IMP-2", "Import Two"]]

    result = dry_run_validate(Tenant, rows, index_to_field)

    assert result.is_valid
    assert result.valid_count == 2
    assert Tenant.objects.filter(code__startswith="IMP-").count() == 0


def test_dry_run_reports_invalid_rows() -> None:
    index_to_field = {0: "code", 1: "name"}
    # Code trop long (max_length=32) -> invalide.
    rows = [["OK-1", "Valide"], ["X" * 40, "Trop long"]]

    result = dry_run_validate(Tenant, rows, index_to_field)

    assert not result.is_valid
    assert result.errors[0].row_index == 1


def test_commit_import_is_all_or_nothing_on_invalid_row() -> None:
    index_to_field = {0: "code", 1: "name"}
    rows = [["ATOMIC-1", "Ligne valide"], ["X" * 40, "Ligne invalide"]]

    with pytest.raises(ValidationError):
        commit_import(Tenant, rows, index_to_field)

    # Aucune ligne n'a ete committee, meme la valide.
    assert not Tenant.objects.filter(code="ATOMIC-1").exists()


def test_commit_import_writes_all_rows_when_all_valid() -> None:
    index_to_field = {0: "code", 1: "name"}
    rows = [["COMMIT-1", "Un"], ["COMMIT-2", "Deux"]]

    count = commit_import(Tenant, rows, index_to_field)

    assert count == 2
    assert Tenant.objects.filter(code__in=["COMMIT-1", "COMMIT-2"]).count() == 2
