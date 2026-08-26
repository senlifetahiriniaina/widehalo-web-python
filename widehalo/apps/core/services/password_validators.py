"""Validation de mot de passe contre une liste locale de mots de passe
compromis (evite une dependance reseau obligatoire vers l'API HIBP,
inadaptee a une connectivite malgache variable — cf. cahier des charges).

Un appel reseau k-anonymity HIBP reste possible en complement (non
implemente ici), mais n'est jamais requis pour que la validation fonctionne.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "compromised_passwords.txt"


@lru_cache(maxsize=1)
def _load_compromised_passwords() -> frozenset[str]:
    if not _DATA_FILE.exists():
        return frozenset()
    with _DATA_FILE.open(encoding="utf-8") as fh:
        return frozenset(line.strip() for line in fh if line.strip())


class CompromisedPasswordValidator:
    """Rejette les mots de passe presents dans la liste locale de mots de
    passe compromis connus."""

    def validate(self, password: str, user: Any = None) -> None:
        if password.lower() in _load_compromised_passwords():
            raise ValidationError(
                _(
                    "Ce mot de passe apparaît dans une liste de mots de passe "
                    "compromis connus. Merci d'en choisir un autre."
                ),
                code="password_compromised",
            )

    def get_help_text(self) -> str:
        return _("Votre mot de passe ne doit pas être un mot de passe compromis connu.")
