"""Écran HTMX/session-authentifié unique du module `analytics` (§12) —
`@login_required`, appel direct aux `services/*` de `analytics`, même
patron que `apps.simulation.views` (cf. sa docstring de tête). Un seul
gabarit à onglets (`analytics/index.html`, budget écrans — même discipline
de consolidation que `pos/index.html`/`simulation/index.html`) : catalogue
du dictionnaire d'indicateurs + état de l'entrepôt (verrou, dernier
rafraîchissement, historique d'exécutions)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.analytics.models import AnMetricDefinition, AnRefreshRun, AnWarehouseState
from apps.analytics.services.dictionary import (
    available_facts,
    list_metrics_for_user,
    register_metric,
)
from apps.analytics.services.refresh import enqueue_refresh
from apps.core.services.rbac_policy import ROLE_APP_PERMISSIONS
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
            # L8 : le dictionnaire cesse d'etre en lecture seule. Les faits
            # et leurs axes viennent de `services/fact_specs.py` par
            # `available_facts()` — jamais recopies dans le gabarit, sans
            # quoi un fait ajoute a l'entrepot cesserait d'etre proposable
            # sans que rien ne le signale.
            "can_edit_metrics": request.user.has_perm("analytics.change_anmetricdefinition"),
            "facts": available_facts(),
            "all_axes": sorted({axis for fact in available_facts() for axis in fact["axes"]}),
            "role_codes": sorted(ROLE_APP_PERMISSIONS),
            "statut_choices": AnMetricDefinition.STATUT_CHOICES,
            "error": request.session.pop("analytics_metric_error", ""),
        },
    )


@login_required
def metric_save(request: HttpRequest) -> HttpResponse:
    """Creation ou nouvelle version d'un indicateur du dictionnaire (L8).

    Le dictionnaire etait consultable et rien d'autre : `register_metric`
    existait, aucun ecran ni endpoint ne l'appelait. Un client ne pouvait
    donc pas ajouter un indicateur a « la SEULE voie declaree d'acces aux
    donnees decisionnelles ».

    Aucune validation n'est refaite ici : le fait et les axes sont valides
    par `register_metric` (contre `fact_specs`), et son `ValidationError`
    est remontee telle quelle a l'ecran. Dupliquer la regle dans la vue
    ferait exactement ce que L8 corrige — une seconde source de verite qui
    finit par diverger."""
    if request.method != "POST" or not request.user.has_perm("analytics.change_anmetricdefinition"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    post = request.POST
    try:
        register_metric(
            tenant,
            code=post.get("code", "").strip(),
            libelle=post.get("libelle", "").strip(),
            module_source=post.get("module_source", "").strip(),
            description=post.get("description", "").strip(),
            formule=post.get("formule", "").strip(),
            unite=post.get("unite", "").strip(),
            fait_source=post.get("fait_source", "").strip(),
            axes_autorises=post.getlist("axes_autorises"),
            roles_autorises=post.getlist("roles_autorises"),
            maille_minimale=post.get("maille_minimale", "").strip(),
            statut=post.get("statut", AnMetricDefinition.STATUT_BROUILLON),
            proprietaire=request.user,
        )
    except ValidationError as exc:
        # Range en session plutot qu'en `?error=` : un message d'erreur
        # dans l'URL survit au rechargement et se partage par copier-coller,
        # ce que le reste du depot evite deja (cf. `stocks.views`).
        request.session["analytics_metric_error"] = "; ".join(exc.messages)
    return redirect("/analytics/?tab=dictionnaire")


@login_required
def refresh_now(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("analytics.add_anrefreshrun"):
        return HttpResponse(status=403)
    enqueue_refresh(resolve_tenant(request))
    return redirect("/analytics/?tab=etat")
