from __future__ import annotations

from decimal import Decimal

from django import template

from apps.core.utils.formatting import format_mga as _format_mga
from apps.core.utils.formatting import format_mga_precise as _format_mga_precise

register = template.Library()


@register.filter(name="mga")
def mga_filter(value: Decimal | int | float | str) -> str:
    return _format_mga(Decimal(str(value)))


@register.filter(name="mga2")
def mga2_filter(value: Decimal | int | float | str) -> str:
    """Meme convention que `mga` (separateur de milliers par espace
    insecable) mais avec exactement 2 decimales — pour une valeur de
    reference/catalogue plutot qu'un solde de caisse, cf.
    `apps.core.utils.formatting.format_mga_precise`."""
    return _format_mga_precise(Decimal(str(value)))
