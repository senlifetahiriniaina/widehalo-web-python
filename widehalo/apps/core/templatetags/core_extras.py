from __future__ import annotations

from typing import Any

from django import template
from django.urls import reverse

register = template.Library()


@register.filter(name="getattr")
def get_attribute(obj: Any, key: str) -> Any:
    """Acces dynamique a un attribut par nom de champ (utilise par le
    composant SmartTable, dont les colonnes sont declarees comme de simples
    chaines cote vue)."""
    return getattr(obj, key, "")


@register.filter(name="dict_get")
def dict_get(mapping: Any, key: str) -> Any:
    """Acces par cle a un dict depuis un template (ex. mesures gradees par
    taille, `patronage/detail.html`) — les templates Django ne permettent
    pas `mapping[key]` avec une variable de boucle directement."""
    if not isinstance(mapping, dict):
        return ""
    return mapping.get(key, "")


@register.filter(name="reverse_with_pk")
def reverse_with_pk(row: Any, url_name: str) -> str:
    """Resout l'URL de detail d'une ligne SmartTable (`row_url_name` passe
    en `page_context`), sans coupler le composant a un module particulier."""
    if not url_name:
        return ""
    return reverse(url_name, args=[row.id])
