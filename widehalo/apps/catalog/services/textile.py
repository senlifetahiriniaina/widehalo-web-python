"""Conversion poids <-> longueur pour un tissu, a partir de son grammage
(g/m², poids surfacique) et de sa laize (largeur, cm) :

    poids (g) = longueur (m) * laize (m) * grammage (g/m2)
    longueur (m) = poids (g) / (laize (m) * grammage (g/m2))
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.catalog.models import TextileSpec

CENTIMETERS_PER_METER = Decimal(100)
GRAMS_PER_KILOGRAM = Decimal(1000)


def _require_dimensions(spec: TextileSpec) -> tuple[Decimal, Decimal]:
    if not spec.weight_gsm or not spec.width_cm:
        raise ValidationError(_("Grammage et laize requis pour la conversion poids/longueur."))
    return spec.weight_gsm, spec.width_cm


def length_from_weight_kg(spec: TextileSpec, weight_kg: Decimal) -> Decimal:
    weight_gsm, width_cm = _require_dimensions(spec)
    width_m = width_cm / CENTIMETERS_PER_METER
    weight_g = weight_kg * GRAMS_PER_KILOGRAM
    return weight_g / (width_m * weight_gsm)


def weight_kg_from_length(spec: TextileSpec, length_m: Decimal) -> Decimal:
    weight_gsm, width_cm = _require_dimensions(spec)
    width_m = width_cm / CENTIMETERS_PER_METER
    weight_g = length_m * width_m * weight_gsm
    return weight_g / GRAMS_PER_KILOGRAM
