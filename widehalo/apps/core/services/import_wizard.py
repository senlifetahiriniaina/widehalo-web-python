from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model


@dataclass
class RowError:
    row_index: int
    errors: dict[str, list[str]]


@dataclass
class DryRunResult:
    valid_count: int
    errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def parse_mapping(header_row: list[str], column_to_field: dict[str, str]) -> dict[int, str]:
    """Associe chaque index de colonne du fichier source au nom de champ
    du modele cible, selon le mapping choisi par l'utilisateur a l'ecran
    d'import (colonne fichier -> champ modele)."""
    index_to_field = {}
    for index, column_name in enumerate(header_row):
        if column_name in column_to_field:
            index_to_field[index] = column_to_field[column_name]
    return index_to_field


def _row_to_field_values(row: list[str], index_to_field: dict[int, str]) -> dict[str, Any]:
    return {
        field_name: row[index] for index, field_name in index_to_field.items() if index < len(row)
    }


def dry_run_validate(
    model: type[Model], rows: list[list[str]], index_to_field: dict[int, str], **extra_fields: Any
) -> DryRunResult:
    """Valide chaque ligne SANS rien ecrire en base (utilise
    `full_clean()` sur une instance non sauvegardee)."""
    errors: list[RowError] = []
    valid_count = 0

    for row_index, row in enumerate(rows):
        field_values = {**_row_to_field_values(row, index_to_field), **extra_fields}
        instance = model(**field_values)
        try:
            instance.full_clean(exclude=set(extra_fields.keys()) or None)
            valid_count += 1
        except ValidationError as exc:
            errors.append(RowError(row_index=row_index, errors=exc.message_dict))

    return DryRunResult(valid_count=valid_count, errors=errors)


def commit_import(
    model: type[Model], rows: list[list[str]], index_to_field: dict[int, str], **extra_fields: Any
) -> int:
    """Import transactionnel atomique : si UNE seule ligne est invalide,
    RIEN n'est committe (tout ou rien) — toujours appeler
    `dry_run_validate()` avant pour presenter les erreurs a l'utilisateur,
    mais `commit_import()` revalide par securite avant d'ecrire."""
    dry_run = dry_run_validate(model, rows, index_to_field, **extra_fields)
    if not dry_run.is_valid:
        raise ValidationError(
            f"{len(dry_run.errors)} ligne(s) invalide(s) — import annulé, rien n'a été enregistré."
        )

    with transaction.atomic():
        count = 0
        for row in rows:
            field_values = {**_row_to_field_values(row, index_to_field), **extra_fields}
            model._default_manager.create(**field_values)
            count += 1
        return count
