"""Écran HTMX/session-authentifié unique du module `analytics` (§12) —
`@login_required`, appel direct aux `services/*` de `analytics`, même
patron que `apps.simulation.views` (cf. sa docstring de tête). Un seul
gabarit à onglets (`analytics/index.html`, budget écrans — même discipline
de consolidation que `pos/index.html`/`simulation/index.html`) : catalogue
du dictionnaire d'indicateurs + état de l'entrepôt (verrou, dernier
rafraîchissement, historique d'exécutions)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.analytics.models import AnMetricDefinition, AnRefreshRun, AnWarehouseState
from apps.analytics.services.dictionary import list_metrics_for_user
from apps.analytics.services.refresh import enqueue_refresh
from apps.core.views.tenant_web import resolve_tenant


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("analytics.view_anmetricdefinition"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    tab = request.GET.get("tab", "dictionnaire")

    metrics: list[AnMetricDefinition] = []
    all_metrics: list[AnMetricDefinition] = []
    state: AnWarehouseState | None = None
    runs: list[AnRefreshRun] = []
    if tab == "etat":
        state = AnWarehouseState.objects.filter(tenant=tenant).first()
        runs = list(AnRefreshRun.objects.filter(tenant=tenant).order_by("-started_at")[:20])
    else:
        metrics = list_metrics_for_user(tenant, request.user)
        if request.user.has_perm("analytics.change_anmetricdefinition"):
            all_metrics = list(
                AnMetricDefinition.objects.filter(tenant=tenant).order_by("module_source", "code")
            )

    return render(
        request,
        "analytics/index.html",
        {
            "tab": tab,
            "metrics": metrics,
            "all_metrics": all_metrics,
            "state": state,
            "runs": runs,
            "can_refresh": request.user.has_perm("analytics.add_anrefreshrun"),
        },
    )


@login_required
def refresh_now(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("analytics.add_anrefreshrun"):
        return HttpResponse(status=403)
    enqueue_refresh(resolve_tenant(request))
    return redirect("/analytics/?tab=etat")
