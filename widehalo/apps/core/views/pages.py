from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.branding import get_tenant_logo_data_uri
from apps.core.services.permissions import user_role_codes
from apps.core.services.search import global_search
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

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


@login_required
def design_system_preview(request: HttpRequest) -> HttpResponse:
    """Ecran de preuve du socle Tailwind/DaisyUI/django-cotton (Sprint 0
    de la refonte UX, cf. docs/planning/2026-refonte-ux-sprints.md) —
    isole du reste de l'application (pas dans la sidebar), reserve a
    admin/direction/superutilisateur le temps que la migration ecran par
    ecran (strangler pattern, B.8 du cahier des charges) commence
    reellement en Sprint 1 (L0)."""
    role_codes = user_role_codes(cast(User, request.user))
    if not (role_codes & _ADMIN_ROLE_CODES or request.user.is_superuser):
        return HttpResponse(status=403)
    return render(request, "tw-design-system-preview.html", {})


@login_required
def company_profile_view(request: HttpRequest) -> HttpResponse:
    """Ecran "Profil de l'entreprise" (chantier marque d'entreprise sur le
    PDF devis/commande) : upload du logo + edition adresse/telephone/e-mail
    du tenant courant. Meme garde de role qu'`settings_page`
    (admin/direction/superutilisateur, defense en profondeur — le lien
    n'est expose que depuis le hub Administration deja garde de meme)."""
    role_codes = user_role_codes(cast(User, request.user))
    if not (role_codes & _ADMIN_ROLE_CODES or request.user.is_superuser):
        return HttpResponse(status=403)

    tenant = resolve_tenant(request)

    if request.method == "POST":
        tenant.address = request.POST.get("address", "")
        tenant.phone = request.POST.get("phone", "")
        tenant.email = request.POST.get("email", "")
        update_fields = ["address", "phone", "email"]
        uploaded_logo = request.FILES.get("logo")
        if uploaded_logo is not None:
            tenant.logo = uploaded_logo
            update_fields.append("logo")
        tenant.save(update_fields=update_fields)
        return redirect("company_profile")

    return render(
        request,
        "company_profile.html",
        {"tenant": tenant, "tenant_logo_data_uri": get_tenant_logo_data_uri(tenant)},
    )
