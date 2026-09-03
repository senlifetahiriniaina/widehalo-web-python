from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.document import Document
from apps.core.models.notification import Notification
from apps.core.models.user import User
from apps.core.services.branding import get_tenant_logo_data_uri
from apps.core.services.permissions import user_role_codes
from apps.core.services.search import global_search
from apps.core.views.smart_table import BulkAction, Column, smart_table_response
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
    queryset = Document.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="core.documents",
        columns=DOCUMENT_COLUMNS,
        queryset=queryset,
        page_template="documents.html",
        # Preuve d'usage de l'action de masse (Sprint 2 / L1, cf.
        # docs/planning/2026-refonte-ux-sprints.md §5) : reutilise
        # `BaseModel.soft_delete()` (deja existant), pas de nouvelle
        # logique d'archivage inventee pour ce lot.
        bulk_actions=[
            BulkAction(
                key="archive",
                label=_("Archiver la sélection"),
                url=reverse("documents_bulk_archive"),
                confirm=_("Archiver les documents sélectionnés ?"),
                danger=True,
            )
        ],
    )


@login_required
def documents_bulk_archive(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)
    ids = request.POST.getlist("ids")
    user = cast(User, request.user)
    for document in Document.objects.filter(id__in=ids):
        document.soft_delete(by=user)
    return redirect("documents")


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


@login_required
def toggle_shell(request: HttpRequest) -> HttpResponse:
    """Bascule le shell applicatif legacy <-> nouveau (Sprint 1 / L0 de la
    refonte UX, strangler pattern — cf.
    docs/planning/2026-refonte-ux-sprints.md §5). Stocke en session (par
    utilisateur, pas par ecran pour l'instant : la granularite par ecran
    viendra avec la migration reelle des lots L3-L9) ; redirige vers `next`
    si fourni et local, sinon vers le referrer, sinon le tableau de bord —
    jamais d'open redirect vers un domaine externe."""
    request.session["use_new_shell"] = not bool(request.session.get("use_new_shell", False))
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    referer = request.META.get("HTTP_REFERER", "")
    if referer.startswith(request.build_absolute_uri("/")):
        return redirect(referer)
    return redirect("dashboard")


@login_required
def launchpad(request: HttpRequest) -> HttpResponse:
    """Launchpad par role (tuiles statiques + dynamiques + KPI, favoris,
    taches recentes — A.7 du cahier des charges refonte UX). Premier ecran
    entierement construit sur le nouveau shell (`<c-shell>`), volontairement
    additif : ne remplace pas `/dashboard/` (qui reste sur l'ancien shell
    tant que L1/L2 n'ont pas livre le moteur de vues et le chatter dont le
    tableau de bord existant a besoin pour migrer proprement).

    Favoris/taches recentes : personnalisation utilisateur reelle (L6,
    `user_preference`) pas encore construite — affiches ici comme
    emplacements vides plutot que simules, pour ne jamais mentir sur l'etat
    du produit.

    Reutilise les 3 compteurs KPI deja construits pour l'ancien tableau de
    bord (`apps.core.views.dashboard.dashboard`) plutot que d'en refaire
    des variantes — memes fonctions publiques, deja tenant-scopees par
    RLS, aucune nouvelle requete inventee pour ce lot.

    Chaque tuile KPI est gardee par `visible_app_labels_for` (meme calcul
    RBAC que le menu/launchpad legacy) : un role sans acces a `crm` ne
    doit jamais voir la tuile "Opportunites CRM ouvertes", meme si elle
    ne fait qu'un COUNT() sans exposer de donnee individuelle — regression
    RBAC reelle detectee par `tests/ui/test_shell_toggle.py::
    test_launchpad_shows_only_role_visible_apps` avant ce correctif."""
    from apps.accounting.services.public import count_unpaid_customer_invoices
    from apps.core.context_processors import visible_app_labels_for
    from apps.crm.services.public import count_open_opportunities
    from apps.sales.services.public import count_orders_pending_confirmation

    user = cast(User, request.user)
    visible = visible_app_labels_for(user)
    unread_notifications = Notification.objects.filter(
        user=user, tenant_id=resolve_tenant(request).id, read_at__isnull=True
    ).count()
    kpis = []
    if "accounting" in visible:
        kpis.append(
            {
                "label": _("Factures clients non soldées"),
                "value": count_unpaid_customer_invoices(),
                "href": "/accounting/",
                "tone": "warning",
            }
        )
    if "crm" in visible:
        kpis.append(
            {
                "label": _("Opportunités CRM ouvertes"),
                "value": count_open_opportunities(),
                "href": "/crm/",
                "tone": "neutral",
            }
        )
    if "sales" in visible:
        kpis.append(
            {
                "label": _("Commandes en attente de confirmation"),
                "value": count_orders_pending_confirmation(),
                "href": "/sales/",
                "tone": "neutral",
            }
        )
    kpis.append(
        {
            "label": _("Notifications non lues"),
            "value": unread_notifications,
            "href": "#",
            "tone": "success" if not unread_notifications else "warning",
        }
    )
    return render(request, "tw-launchpad.html", {"kpis": kpis})


@login_required
def notifications_bell_fragment(request: HttpRequest) -> HttpResponse:
    """Cloche de notifications (compteur live via polling HTMX — A.7 du
    cahier des charges). Vue Django classique (pas django-ninja) : le
    fragment est charge par la session du navigateur comme le reste du
    shell, alors que `apps.core.api_notifications` sert un public JWT
    distinct (mobile/IA) — meme partition que le reste du depot entre
    endpoints HTMX et API publique (cf. docs/planning/ECART_ARCHITECTURE.md
    §3)."""
    user = cast(User, request.user)
    tenant_id = resolve_tenant(request).id
    notifications = Notification.objects.filter(user=user, tenant_id=tenant_id).order_by(
        "-created_at"
    )[:10]
    unread_count = Notification.objects.filter(
        user=user, tenant_id=tenant_id, read_at__isnull=True
    ).count()
    return render(
        request,
        "components/_notification_bell.html",
        {"notifications": notifications, "unread_count": unread_count},
    )


@login_required
def notification_mark_read(request: HttpRequest, notification_id: str) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)
    Notification.objects.filter(
        id=notification_id,
        user=cast(User, request.user),
        tenant_id=resolve_tenant(request).id,
    ).update(read_at=timezone.now())
    return notifications_bell_fragment(request)
