from __future__ import annotations

from typing import Any

from django import template

register = template.Library()


@register.filter(name="getattr")
def get_attribute(obj: Any, key: str) -> Any:
    """Acces dynamique a un attribut par nom de champ (utilise par le
    composant SmartTable, dont les colonnes sont declarees comme de simples
    chaines cote vue)."""
    return getattr(obj, key, "")
