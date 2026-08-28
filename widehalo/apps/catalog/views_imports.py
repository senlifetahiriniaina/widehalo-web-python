"""Ecran d'import du catalogue (session HTMX, jamais l'API JWT en interne)
— meme discipline que `apps.accounting.views_imports`, regroupe sous le
hub "Configuration Catalogue" existant (`views_config.config_index`)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.catalog.services.catalog_import import import_catalog_xlsx
from apps.core.views.tenant_web import resolve_tenant


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
