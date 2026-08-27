"""Garde-fou bloquant (couche 7, T4/MIG du CDC) : aucun modele ne doit
diverger silencieusement des migrations versionnees. Une derive non
detectee ici casse `django-test-migrations` (qui rejoue l'historique reel
des migrations) et le zero-downtime deploy (expand/migrate/contract, cf.
tests/migrations/test_mig1_expand_contract.py).

Ne JAMAIS contourner un echec ici en generant une migration jetable sans
comprendre le changement de modele qui la declenche."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command


@pytest.mark.django_db
def test_no_missing_migrations() -> None:
    """Equivalent de `manage.py makemigrations --check --dry-run` : leve
    une CommandError (ou ecrit des operations manquantes) des qu'un champ
    de modele n'a pas sa migration correspondante."""
    output = StringIO()
    try:
        call_command(
            "makemigrations",
            "--check",
            "--dry-run",
            stdout=output,
            stderr=output,
        )
    except (CommandError, SystemExit) as exc:  # pragma: no cover - chemin d'echec
        raise AssertionError(
            "Des changements de modele n'ont pas de migration associee "
            f"(makemigrations --check --dry-run a echoue) :\n{output.getvalue()}"
        ) from exc
