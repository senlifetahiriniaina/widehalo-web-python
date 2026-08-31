"""REF1 (enrichissement referentiel LIFE MDG, cf. plan) : validation du
format de code Pantone (`pantone_code`) sur `AttributeValue`.

**Reserve legale explicite** (cf. plan) : le nuancier Pantone FHI Cotton
TCX (2 801 teintes) est une base de donnees commerciale sous licence, pas
une norme publique librement redistribuable. Ce module valide UNIQUEMENT
le **format** du code (`NN-NNNN TCX`, ex. `19-4052 TCX`) par une simple
expression reguliere — il ne contient et ne consulte AUCUNE table de
correspondance code<->RGB/hex propriétaire Pantone. `hex_approximation`
n'est jamais deduit automatiquement d'un `pantone_code` par ce module :
c'est une saisie manuelle libre de l'utilisateur, ou rien.

Meme discipline que `services/sector_specs.py` : validation en service
(pas de `RegexValidator` au niveau modele), point d'entree unique de
mutation, jamais de mutation directe du champ depuis une vue/API."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.catalog.models import AttributeValue

_PANTONE_CODE_PATTERN = re.compile(r"^\d{2}-\d{4} TCX$")
_HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_pantone_code(pantone_code: str) -> None:
    """Leve `ValidationError` si `pantone_code` (une fois non vide) ne
    respecte pas le format `NN-NNNN TCX` du nuancier Pantone FHI Cotton
    TCX. Une chaine vide est toujours valide (champ optionnel)."""
    if pantone_code and not _PANTONE_CODE_PATTERN.match(pantone_code):
        raise ValidationError(
            _(
                "Le code Pantone doit respecter le format 'NN-NNNN TCX' "
                "(ex. '19-4052 TCX'), reçu : %(value)s"
            )
            % {"value": pantone_code}
        )


def validate_hex_approximation(hex_approximation: str) -> None:
    """Leve `ValidationError` si `hex_approximation` (une fois non vide)
    n'est pas un code hexadecimal `#RRGGBB` valide. Ne verifie QUE la
    forme — cette valeur est une approximation saisie manuellement par
    l'utilisateur, jamais une valeur sourcee du nuancier Pantone."""
    if hex_approximation and not _HEX_PATTERN.match(hex_approximation):
        raise ValidationError(_("L'approximation hexadécimale doit respecter le format '#RRGGBB'."))


def set_attribute_value_color_reference(
    attribute_value: AttributeValue,
    *,
    pantone_code: str = "",
    hex_approximation: str = "",
) -> AttributeValue:
    """Point d'entree unique de mise a jour de la reference couleur d'une
    `AttributeValue` — valide toujours le format avant persistance (jamais
    de mutation directe depuis une vue/API)."""
    validate_pantone_code(pantone_code)
    validate_hex_approximation(hex_approximation)
    attribute_value.pantone_code = pantone_code
    attribute_value.hex_approximation = hex_approximation
    attribute_value.full_clean()
    attribute_value.save(update_fields=["pantone_code", "hex_approximation", "updated_at"])
    return attribute_value
