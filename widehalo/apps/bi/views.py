"""Écrans HTMX/session-authentifiés du module `bi` (§13.1) —
`@login_required`, appel direct aux `services/*` de `bi`/`analytics`, même
patron que `apps.simulation.views`/`apps.analytics.views`.

**Deux gabarits** (budget écrans, même discipline de consolidation que
`pos/index.html`/`simulation/index.html`) : `bi/index.html` (tableaux de
bord / catalogue / journal de rafraîchissement+diffusion / gouvernance du
dictionnaire, à onglets `?tab=`), `bi/report_detail.html` (un rapport :
définition, résultats, exploration du détail, export, diffusion).

**Constructeur self-service (BI-2)** : un `<textarea>` JSON décrivant
`{"metric_codes", "dimensions", "filters", "chart_type"}` plutôt qu'un
formulaire dynamique par indicateur — même choix minimal-viable que
`apps.reporting.views.generate_form` (cf. sa docstring, RPT-12 explicitement
différé en V2). « Aucun champ libre » (BI-2) porte sur l'ABSENCE de SQL/
fragment de requête, pas sur la forme de saisie : le JSON reste une simple
LISTE de codes déjà déclarés, jamais interprété comme du code — validé
côté serveur par `services/query.py` à CHAQUE exécution, jamais fait
confiance tel quel."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from apps.analytics.services.public import (
    get_latest_refresh_summary,
    list_metric_versions,
    list_published_metrics,
)
from apps.bi.models import BiDashboard, BiDiffusionLog, BiReport
from apps.bi.services.diffusion import compute_next_run_at
from apps.bi.services.export import REPORT_CODE
from apps.bi.services.query import drill_down, run_report
from apps.core.tenant_context import activate_tenant
from apps.core.views.tenant_web import resolve_tenant


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("bi.view_bireport"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    tab = request.GET.get("tab", "dashboards")
    context = {"tab": tab, "can_manage": request.user.has_perm("bi.add_bireport")}

    if tab == "catalogue":
        context["reports"] = BiReport.objects.filter(tenant=tenant, is_published=True)
    elif tab == "journal":
        context["refresh_summary"] = get_latest_refresh_summary(tenant)
        context["diffusion_logs"] = list(
            BiDiffusionLog.objects.filter(tenant=tenant)
            .select_related("report")
            .order_by("-sent_at")[:30]
        )
    elif tab == "gouvernance":
        context["metrics"] = list_published_metrics(tenant, request.user)
    else:
        role_codes = set(request.user.groups.values_list("name", flat=True))
        context["dashboards"] = BiDashboard.objects.filter(tenant=tenant).filter(
            Q(owner=request.user) | Q(role_code__in=role_codes) | Q(is_shared=True)
        )
        context["reports_by_id"] = {
            str(r.id): r for r in BiReport.objects.filter(tenant=tenant, is_published=True)
        }
    return render(request, "bi/index.html", context)


@login_required
def metric_history(request: HttpRequest, code: str) -> HttpResponse:
    """BI-9 : historique des versions d'un indicateur (« conserve la
    précédente »)."""
    if not request.user.has_perm("bi.view_bireport"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    versions = list_metric_versions(tenant, code)
    # Conteneur jsonb Postgres (`__contains`) : liste les rapports dont
    # `definition.metric_codes` inclut cet indicateur (BI-9, "liste les
    # rapports impactés") — jamais une interprétation de `definition`
    # comme autre chose qu'une donnée à filtrer.
    impacted_reports = list(
        BiReport.objects.filter(tenant=tenant, definition__metric_codes__contains=[code])
    )
    return render(
        request,
        "bi/_metric_history.html",
        {"code": code, "versions": versions, "impacted_reports": impacted_reports},
    )


@login_required
def report_new(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("bi.add_bireport"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    error = ""
    if request.method == "POST":
        try:
            definition = json.loads(request.POST.get("definition_json") or "{}")
            name = request.POST.get("name", "").strip()
            if not name:
                raise ValidationError("Le nom est obligatoire.")
            with activate_tenant(tenant.id):
                report = BiReport.objects.create(
                    tenant=tenant,
                    code=slugify(name)[:64] or "rapport",
                    name=name,
                    domaine=request.POST.get("domaine", "").strip(),
                    owner=request.user,
                    definition=definition,
                    created_by=request.user,
                )
            return redirect("bi:report_detail", report_id=report.id)
        except (json.JSONDecodeError, ValidationError) as exc:
            error = str(exc)
    return render(request, "bi/report_detail.html", {"report": None, "error": error})


@login_required
def report_detail(request: HttpRequest, report_id: str) -> HttpResponse:
    report = get_object_or_404(BiReport, id=report_id)
    if not request.user.has_perm("bi.view_bireport"):
        return HttpResponse(status=403)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_definition":
            if not request.user.has_perm("bi.change_bireport"):
                return HttpResponse(status=403)
            try:
                report.definition = json.loads(request.POST.get("definition_json") or "{}")
                report.is_published = bool(request.POST.get("is_published"))
                report.save(update_fields=["definition", "is_published"])
            except json.JSONDecodeError as exc:
                return render(
                    request,
                    "bi/report_detail.html",
                    _report_context(report, request.user, error=str(exc)),
                )
        elif action == "update_diffusion":
            if not request.user.has_perm("bi.change_bireport"):
                return HttpResponse(status=403)
            report.diffusion_enabled = bool(request.POST.get("diffusion_enabled"))
            report.diffusion_frequency = request.POST.get("diffusion_frequency", "")
            recipients_raw = request.POST.get("diffusion_recipients", "")
            report.diffusion_recipients = [
                e.strip() for e in recipients_raw.split(",") if e.strip()
            ]
            if (
                report.diffusion_enabled
                and report.diffusion_frequency
                and not report.diffusion_next_run_at
            ):
                report.diffusion_next_run_at = compute_next_run_at(report.diffusion_frequency)
            report.save(
                update_fields=[
                    "diffusion_enabled",
                    "diffusion_frequency",
                    "diffusion_recipients",
                    "diffusion_next_run_at",
                ]
            )
        return redirect("bi:report_detail", report_id=report.id)

    return render(request, "bi/report_detail.html", _report_context(report, request.user))


def _report_context(report: BiReport, user, *, error: str = "") -> dict:
    result = run_report(report.tenant, report, user)
    return {
        "report": report,
        "result": result,
        "error": error,
        "can_change": user.has_perm("bi.change_bireport"),
        "definition_json": json.dumps(report.definition, ensure_ascii=False),
    }


@login_required
def report_drill_down(request: HttpRequest, report_id: str) -> JsonResponse:
    """BI-10 : depuis une valeur agrégée, atteint les lignes qui la
    composent — AJAX, appelé depuis un clic sur une cellule du tableau."""
    report = get_object_or_404(BiReport, id=report_id)
    if not request.user.has_perm("bi.view_bireport"):
        return JsonResponse({"detail": "forbidden"}, status=403)
    metric_code = request.GET.get("metric_code", "")
    try:
        cell_filters = json.loads(request.GET.get("cell_filters") or "[]")
    except json.JSONDecodeError:
        cell_filters = []
    result = drill_down(
        report.tenant, report, request.user, metric_code=metric_code, cell_filters=cell_filters
    )
    return JsonResponse(result)


@login_required
def report_export(request: HttpRequest, report_id: str) -> HttpResponse:
    """BI-8 : export asynchrone — réutilise entièrement `apps.reporting`
    (cf. docstring `services/export.py`), redirige vers son écran de
    suivi/téléchargement déjà existant (`reporting:job_status`)."""
    if request.method != "POST":
        return HttpResponse(status=403)
    report = get_object_or_404(BiReport, id=report_id)
    if not request.user.has_perm("bi.view_bireport"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    format = request.POST.get("format", "xlsx")

    from apps.reporting.services.public import enqueue_report_generation

    with activate_tenant(tenant.id):
        job = enqueue_report_generation(
            code=REPORT_CODE,
            params={"bi_report_id": str(report.id)},
            format=format,
            lang=request.user.preferred_language,
            actor=request.user,
            tenant_id=str(tenant.id),
        )
    return redirect("reporting:job_status", job_id=job["job_id"])
