"""Ecran d'import du catalogue (session HTMX, jamais l'API JWT en interne)
— meme discipline que `apps.accounting.views_imports`, regroupe sous le
hub "Configuration Catalogue" existant (`views_config.config_index`)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.catalog.services.catalog_import import import_catalog_xlsx
from apps.core.services.import_xlsx import build_xlsx_template
from apps.core.views.tenant_web import resolve_tenant


@login_required
def download_catalog_template(request: HttpRequest) -> HttpResponse:
    data = build_xlsx_template(
        [
            "Code",
            "Nom",
            "Catégorie",
            "Unité de mesure",
            "Attributs de variantes",
            "Matière",
            "Composition",
            "Grammage",
            "Laize",
        ],
        example_row=[
            "TPL-0001",
            "T-shirt coton",
            "Vêtements",
            "PCE",
            "couleur=bleu;taille=M",
            "Coton",
            "100% coton",
            180,
            150,
        ],
    )
    response = HttpResponse(
        data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="modele_import_catalogue.xlsx"'
    return response


@login_required
def imports_catalog(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_catalog_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    return render(
        request,
        "catalog/imports.html",
        {"summary": summary, "error": error},
    )
