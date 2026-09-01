"""SmartTable : composant transversal de liste server-side (tri, filtre,
pagination, colonnes masquables, vues sauvegardees, export) — reutilise par
tous les ecrans de liste des modules metier. Rendu par HTMX : une requete
HTMX ne renvoie que le fragment (`_smart_table.html`), jamais la page
complete, pour respecter la contrainte « aucune interaction ne recharge la
page complete »."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string

from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User
from apps.core.services.export import export_queryset
from apps.core.services.permissions import user_role_codes
from apps.core.utils.formatting import COLUMN_FORMATTERS

ALLOWED_PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 25
EXPORT_FORMATS = ("csv", "xlsx", "pdf")

# Formats de colonne consideres numeriques — alignes a droite cote template
# (`_smart_table.html`), jamais code en dur par module (ex. "bool" reste
# aligne a gauche, ce n'est pas un montant).
NUMERIC_COLUMN_FORMATS = frozenset({"mga"})

_EXPORT_CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def smart_table_dom_id(table_key: str) -> str:
    """Derive un id HTML/CSS-safe depuis `table_key` (chaine a points type
    ``"catalog.templates"``) — SEULE fonction faisant autorite pour cette
    derivation, reutilisee cote template via le filtre `smart_table_dom_id`
    (`core_extras.py`). Ne renomme JAMAIS `table_key` lui-meme : cette valeur
    reste stockee telle quelle dans `SavedTableView.table_key` (scope des
    vues sauvegardees) — seule sa representation HTML derivee change ici.

    Correctif systemique : un point non echappe dans un selecteur CSS
    (`#smart-table-catalog.templates`) est interprete comme
    `id=smart-table-catalog` + `class=templates`, jamais comme un id
    contenant un point litteral — ce qui cassait silencieusement recherche/
    tri/pagination HTMX sur la quasi-totalite des ~198 ecrans de liste."""
    return "smart-table-" + re.sub(r"[^a-zA-Z0-9_-]", "-", table_key)


@dataclass
class Column:
    key: str
    label: str
    searchable: bool = True
    format: str | None = None


def visible_saved_views(user: User, table_key: str) -> QuerySet[SavedTableView]:
    """RPT-SAVE1 (§5.11) : une vue sauvegardee visible pour `user` est soit
    personnelle (owner = `user`), soit partagee avec l'un de ses roles
    (`shared_with_role`) — jamais les deux filtres requis a la fois."""
    return SavedTableView.objects.filter(table_key=table_key).filter(
        Q(owner=user) | Q(shared_with_role__in=user_role_codes(user))
    )


def _humanize_table_key(table_key: str) -> str:
    """Derive un titre lisible depuis `table_key` (ex. "catalog.templates"
    -> "Catalog templates") pour l'entete des exports PDF — un libelle
    exact par ecran n'est pas fourni par les ~198 appelants existants,
    cette derivation automatique reste meilleure qu'un titre absent."""
    words = re.split(r"[._-]+", table_key)
    return " ".join(w.capitalize() for w in words if w)


def _format_export_cell(row: Any, column: Column) -> str:
    value = getattr(row, column.key, "")
    if column.format:
        formatter = COLUMN_FORMATTERS.get(column.format)
        if formatter is not None:
            try:
                return str(formatter(value))
            except (ValueError, TypeError):
                pass
    return "" if value is None else str(value)


def _export_response(
    request: HttpRequest,
    *,
    export_format: str,
    table_key: str,
    columns: list[Column],
    queryset: QuerySet[Any],
) -> HttpResponse:
    filename = f"{table_key}.{export_format}"
    if export_format in ("csv", "xlsx"):
        field_names = [c.key for c in columns]
        payload = export_queryset(queryset, field_names, format=export_format)
    else:
        # PDF : reutilise le gabarit partage `reports/_base.html` (entete +
        # pied de page "WideHalo" deja normalises pour tout rapport de ce
        # depot) — jamais une mise en page ad hoc par ecran.
        company = Tenant.objects.first()
        rows = [[_format_export_cell(row, column) for column in columns] for row in queryset]
        html = render_to_string(
            "reports/smart_table_export.html",
            {
                "title": _humanize_table_key(table_key),
                "company_name": company.name if company else "",
                "column_labels": [c.label for c in columns],
                "rows": rows,
            },
        )
        from weasyprint import HTML

        payload = HTML(string=html).write_pdf()

    response = HttpResponse(payload, content_type=_EXPORT_CONTENT_TYPES[export_format])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _apply_search(queryset: QuerySet[Any], columns: list[Column], query: str) -> QuerySet[Any]:
    if not query:
        return queryset
    condition = Q()
    for column in columns:
        if column.searchable:
            condition |= Q(**{f"{column.key}__icontains": query})
    return queryset.filter(condition) if condition else queryset


def smart_table_response(
    request: HttpRequest,
    *,
    table_key: str,
    columns: list[Column],
    queryset: QuerySet[Any],
    page_template: str,
    page_context: dict[str, Any] | None = None,
) -> HttpResponse:
    query = request.GET.get("q", "")
    sort = request.GET.get("sort", "")
    hidden = set(request.GET.getlist("hide"))
    page_number = request.GET.get("page", "1")

    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE
    if page_size not in ALLOWED_PAGE_SIZES:
        page_size = DEFAULT_PAGE_SIZE

    queryset = _apply_search(queryset, columns, query)
    queryset = queryset.order_by(sort) if sort else queryset.order_by("-created_at")

    export_format = request.GET.get("export")
    if export_format in EXPORT_FORMATS:
        return _export_response(
            request,
            export_format=export_format,
            table_key=table_key,
            columns=columns,
            queryset=queryset,
        )

    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)

    visible_columns = [c for c in columns if c.key not in hidden]
    # SmartTable est toujours servi derriere `@login_required` dans les vues
    # appelantes ; ce cast satisfait django-stubs (`request.user` est type
    # `User | AnonymousUser` par defaut).
    saved_views = visible_saved_views(cast(User, request.user), table_key)

    context = {
        "table_key": table_key,
        "columns": visible_columns,
        "all_columns": columns,
        "hidden_columns": hidden,
        "page_obj": page_obj,
        "query": query,
        "sort": sort,
        "page_size": page_size,
        "page_size_options": ALLOWED_PAGE_SIZES,
        "saved_views": saved_views,
        **(page_context or {}),
    }

    fragment = "components/_smart_table.html"
    if getattr(request, "htmx", False):
        return render(request, fragment, context)
    return render(request, page_template, context)
