from __future__ import annotations

from decimal import Decimal

from django import template

from apps.core.utils.formatting import format_mga as _format_mga

register = template.Library()


@register.filter(name="mga")
def mga_filter(value: Decimal | int | float | str) -> str:
    return _format_mga(Decimal(str(value)))
