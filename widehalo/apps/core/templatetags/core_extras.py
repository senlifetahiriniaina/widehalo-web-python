from __future__ import annotations

from decimal import InvalidOperation
from typing import Any

from django import template
from django.http import QueryDict
from django.urls import reverse

from apps.core.utils.formatting import COLUMN_FORMATTERS
from apps.core.views.smart_table import smart_table_dom_id as _smart_table_dom_id

register = template.Library()


@register.filter(name="getattr")
def get_attribute(obj: Any, key: str) -> Any:
    """Acces dynamique a un attribut par nom de champ (utilise par le
    composant SmartTable, dont les colonnes sont declarees comme de simples
    chaines cote vue)."""
    return getattr(obj, key, "")


@register.filter(name="smart_table_dom_id")
def smart_table_dom_id(table_key: str) -> str:
    """Re-exporte `apps.core.views.smart_table.smart_table_dom_id` — seul
    point de verite pour l'id HTML/CSS-safe derive de `table_key`, jamais
    recalcule independamment cote template."""
    return _smart_table_dom_id(table_key)


@register.filter(name="smart_table_format")
def smart_table_format(value: Any, format_key: str | None) -> Any:
    """Applique le formateur enregistre sous `format_key` dans
    `COLUMN_FORMATTERS` (ex. "mga") — passthrough si `format_key` est vide/
    non enregistre, jamais une erreur 500 sur un ecran de liste partage par
    ~198 ecrans en cas de valeur malformee."""
    if not format_key:
        return value
    formatter = COLUMN_FORMATTERS.get(format_key)
    if formatter is None:
        return value
    try:
        return formatter(value)
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.simple_tag(name="smart_table_query")
def smart_table_query(
    query: str = "",
    hide: Any = None,
    sort: str = "",
    page_size: Any = None,
    page: Any = None,
    export: str | None = None,
) -> str:
    """Construit une chaine de requete correctement encodee pour les liens
    HTMX de SmartTable (recherche/tri/pagination/export), en preservant
    explicitement `q`/`hide`/`sort`/`page_size` selon le lien — remplace les
    concatenations manuelles `?...&q={{ query }}` qui perdaient
    silencieusement les colonnes masquees/le tri actif en paginant, et
    n'echappaient jamais `query`."""
    qd = QueryDict(mutable=True)
    if query:
        qd["q"] = query
    if hide:
        qd.setlist("hide", list(hide))
    if sort:
        qd["sort"] = sort
    if page_size is not None:
        qd["page_size"] = str(page_size)
    if page is not None:
        qd["page"] = str(page)
    if export:
        qd["export"] = export
    return qd.urlencode()


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


_BADGE_SUCCESS_TOKENS = (
    "paid",
    "payee",
    "paye",
    "validated",
    "valide",
    "confirmed",
    "confirme",
    "resolved",
    "resolue",
    "resolu",
    "active",
    "actif",
    "done",
    "termine",
    "closed",
    "cloture",
    "delivered",
    "livre",
    "won",
    "gagne",
    "achieved",
    "on_track",
    "posted",
    "approved",
    "approuve",
)
_BADGE_WARNING_TOKENS = (
    "sent",
    "envoye",
    "pending",
    "attente",
    "in_progress",
    "in_transit",
    "en_cours",
    "to_validate",
    "a_valider",
    "draft",
    "brouillon",
    "partially",
    "partiel",
    "at_risk",
    "suggested",
    "submitted",
    "escalated",
)
_BADGE_DANGER_TOKENS = (
    "cancelled",
    "canceled",
    "annule",
    "failed",
    "echoue",
    "echec",
    "rejected",
    "refuse",
    "blocked",
    "bloque",
    "overdue",
    "en_retard",
    "lost",
    "perdu",
    "missed",
    "off_track",
    "dispute",
    "litige",
    "unresolvable",
    "expired",
    "expire",
    "revoked",
    "revoque",
)


@register.filter(name="state_badge_class")
def state_badge_class(value: Any) -> str:
    """Heuristique de correspondance de sous-chaines entre une valeur d'etat
    (state/status brut ou libelle affiche) et une variante de couleur de
    `.badge` (cf. static/css/app.css) — pas de table de correspondance par
    module, un simple filtre reutilisable sur tout ecran (chantier UX5)."""
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized:
        return "b-neutral"
    for token in _BADGE_DANGER_TOKENS:
        if token in normalized:
            return "b-fail"
    for token in _BADGE_SUCCESS_TOKENS:
        if token in normalized:
            return "b-success"
    for token in _BADGE_WARNING_TOKENS:
        if token in normalized:
            return "b-pending"
    return "b-neutral"
