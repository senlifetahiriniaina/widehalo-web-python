from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Page d'accueil — volontairement legere (3 tuiles KPI + quelques
    liens), aucun tableau lourd, pour respecter le budget de 200 Ko
    compresse. Les 3 compteurs sont deja tenant-scopes par RLS via les
    managers `objects` par defaut (aucune requete supplementaire hors
    contexte tenant, aucun nouveau modele/endpoint — chantier UX6)."""
    from apps.accounting.services.public import count_unpaid_customer_invoices
    from apps.crm.services.public import count_open_opportunities
    from apps.sales.services.public import count_orders_pending_confirmation

    unpaid_invoices = count_unpaid_customer_invoices()
    open_opportunities = count_open_opportunities()
    orders_pending_confirmation = count_orders_pending_confirmation()

    kpis = [
        {"label": _("Factures clients non soldees"), "value": unpaid_invoices},
        {"label": _("Opportunites CRM ouvertes"), "value": open_opportunities},
        {"label": _("Commandes en attente de confirmation"), "value": orders_pending_confirmation},
    ]
    return render(request, "dashboard.html", {"kpis": kpis})
