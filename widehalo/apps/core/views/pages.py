from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.permissions import user_role_codes
from apps.core.services.search import global_search
from apps.core.views.smart_table import Column, smart_table_response

_ADMIN_ROLE_CODES = {"admin", "direction"}

DOCUMENT_COLUMNS = [
    Column(key="original_name", label="Nom du fichier"),
    Column(key="mime_type", label="Type", searchable=False),
]


@login_required
def search_page(request: HttpRequest) -> HttpResponse:
    return render(request, "search.html", {})


@login_required
def instant_search_fragment(request: HttpRequest) -> HttpResponse:
    """Selecteur avec recherche instantanee (composant transversal) :
    appele en HTMX a chaque frappe (`hx-trigger="keyup changed delay:300ms"`),
    ne renvoie jamais qu'un fragment de resultats."""
    query = request.GET.get("q", "")
    tenant_id = request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""
    results = global_search(query, user=cast(User, request.user), tenant_id=tenant_id)
    return render(request, "components/_instant_search_results.html", {"results": results})


@login_required
def documents_list(request: HttpRequest) -> HttpResponse:
    queryset = Document.objects.all()
    return smart_table_response(
        request,
        table_key="core.documents",
        columns=DOCUMENT_COLUMNS,
        queryset=queryset,
        page_template="documents.html",
    )


@login_required
def settings_page(request: HttpRequest) -> HttpResponse:
    """Hub « Administration » (config des modules metier) — restreint a
    admin/direction/superutilisateur (chantier menu compte utilisateur /
    section Administration signale par l'utilisateur). Garde en defense en
    profondeur : le lien sidebar est deja masque pour les autres roles via
    `is_admin_user` (context processor `apps.core.context_processors.
    account`), mais la vue reste protegee meme sur un acces direct devine."""
    role_codes = user_role_codes(cast(User, request.user))
    if not (role_codes & _ADMIN_ROLE_CODES or request.user.is_superuser):
        return HttpResponse(status=403)
    return render(request, "settings.html", {})
