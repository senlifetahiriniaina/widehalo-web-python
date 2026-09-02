from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Page d'accueil — volontairement legere (3 tuiles KPI + quelques
    liens), aucun tableau lourd, pour respecter le budget de 200 Ko
    compresse. Les 3 compteurs sont deja tenant-scopes par RLS via les
    managers `objects` par defaut (aucune requete supplementaire hors
    contexte tenant, aucun nouveau modele/endpoint — chantier UX6).

    Redirige vers le nouveau launchpad (Sprint 1 / L0 de la refonte UX)
    si l'utilisateur a bascule le shell — cf.
    `apps.core.views.pages.toggle_shell`/`launchpad`. Reste l'ecran
    d'accueil par defaut (ancien shell) tant que le flag n'est pas actif,
    coherent avec le strangler pattern (B.8 du cahier des charges) : rien
    ne change pour un utilisateur qui n'a pas explicitement essaye la
    nouvelle interface."""
    if request.session.get("use_new_shell"):
        return redirect("launchpad")

    from apps.accounting.services.public import count_unpaid_customer_invoices
    from apps.crm.services.public import count_open_opportunities
    from apps.sales.services.public import count_orders_pending_confirmation

    unpaid_invoices = count_unpaid_customer_invoices()
    open_opportunities = count_open_opportunities()
    orders_pending_confirmation = count_orders_pending_confirmation()

    kpis = [
        {"label": _("Factures clients non soldées"), "value": unpaid_invoices},
        {"label": _("Opportunités CRM ouvertes"), "value": open_opportunities},
        {"label": _("Commandes en attente de confirmation"), "value": orders_pending_confirmation},
    ]
    return render(request, "dashboard.html", {"kpis": kpis})
