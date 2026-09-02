"""SmartTable : composant transversal de liste server-side (tri, filtre,
pagination, colonnes masquables, vues sauvegardees, export) — reutilise par
tous les ecrans de liste des modules metier. Rendu par HTMX : une requete
HTMX ne renvoie que le fragment (`_smart_table.html`), jamais la page
complete, pour respecter la contrainte « aucune interaction ne recharge la
page complete »."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string

from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User
from apps.core.services.permissions import user_role_codes
from apps.core.utils.formatting import COLUMN_FORMATTERS
from apps.core.views.tenant_web import resolve_tenant

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


@dataclass
class BulkAction:
    """Action de masse (Sprint 2 / L1, cf. docs/planning/2026-refonte-ux-sprints.md
    §5) — case a cocher par ligne + case "tout selectionner", jamais recolte
    en JS : un `<form method="post">` natif porte les ids coches
    (`name="ids"`), soumis vers `url` via le bouton correspondant
    (`formaction`) — fonctionne sans JavaScript (A.10 du cahier des
    charges, progressive enhancement), Alpine se contente d'activer/
    desactiver les boutons selon le nombre coche."""

    key: str
    label: str
    url: str
    confirm: str | None = None
    danger: bool = False


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
    field_names = [c.key for c in columns]
    # Construit les lignes via `getattr` (comme le rendu de cellule normal du
    # tableau, `_format_export_cell`) plutot que `queryset.values(*field_names)`
    # — une colonne appuyee sur une `@property` de modele (ex.
    # `Partner.roles_display`, jamais un vrai champ de requete) ferait
    # echouer `.values()` avec un `FieldError` a l'export, alors que le
    # rendu HTML de la meme colonne fonctionne deja sans probleme.
    rows = [[_format_export_cell(row, column) for column in columns] for row in queryset]

    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(field_names)
        writer.writerows(rows)
        payload: bytes = buffer.getvalue().encode("utf-8")
    elif export_format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(field_names)
        for row in rows:
            sheet.append(row)
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        payload = buffer_bytes.getvalue()
    else:
        # PDF : reutilise le gabarit partage `reports/_base.html` (entete +
        # pied de page "WideHalo" deja normalises pour tout rapport de ce
        # depot) — jamais une mise en page ad hoc par ecran.
        company = Tenant.objects.first()
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
    bulk_actions: list[BulkAction] | None = None,
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
        "bulk_actions": bulk_actions or [],
        **(page_context or {}),
    }

    fragment = "components/_smart_table.html"
    if getattr(request, "htmx", False):
        return render(request, fragment, context)
    return render(request, page_template, context)


@login_required
def save_current_view(request: HttpRequest) -> HttpResponse:
    """Enregistre l'etat courant d'un SmartTable (recherche/tri/colonnes
    masquees) en `SavedTableView` — ferme la boucle CRUD signalee manquante
    au Sprint 2 (L1) : le moteur de lecture des vues sauvegardees existait
    deja (`visible_saved_views`), aucune UI ne permettait d'en creer une.
    Mapping deliberement minimal (pas de filtres par champ, qui n'existent
    pas encore cote SmartTable — seulement la recherche texte globale) :
    `filters` = `{"q": ...}`, `columns` = colonnes masquees (pas visibles :
    coherent avec `hide=` de la querystring, la liste des colonnes
    disponibles evolue avec le code, pas avec la vue sauvegardee)."""
    if request.method != "POST":
        return HttpResponse(status=405)

    table_key = request.POST.get("table_key", "")
    name = request.POST.get("name", "").strip()
    if not table_key or not name:
        return HttpResponse(status=400)

    SavedTableView.objects.update_or_create(
        tenant=resolve_tenant(request),
        owner=cast(User, request.user),
        table_key=table_key,
        name=name,
        defaults={
            "columns": request.POST.getlist("hide"),
            "filters": {"q": request.POST.get("q", "")},
            "sort": request.POST.get("sort", ""),
        },
    )

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard")
