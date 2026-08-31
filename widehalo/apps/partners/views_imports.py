"""Ecran d'import du referentiel partenaires (session HTMX, jamais l'API
JWT en interne) — meme discipline que
`apps.accounting.views_imports`. `partners` n'a pas de hub "Configuration"
dedie (contrairement a `accounting`/`catalog`/`stocks`) : l'ecran est
rattache directement au menu partenaires (`templates/partners/list.html`),
seul point d'entree existant du module."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.core.services.import_xlsx import build_xlsx_template
from apps.core.views.tenant_web import resolve_tenant
from apps.partners.services.partner_import import import_partners_xlsx


@login_required
def download_partner_template(request: HttpRequest) -> HttpResponse:
    data = build_xlsx_template(
        ["Code", "Nom", "NIF", "Roles", "Plafond de crédit"],
        example_row=["PART-0001", "Client Exemple SARL", "1234567890", "client", 500000],
    )
    response = HttpResponse(
        data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="modele_import_partenaires.xlsx"'
    return response


@login_required
def imports_partners(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_partners_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    return render(
        request,
        "partners/imports.html",
        {"summary": summary, "error": error},
    )
