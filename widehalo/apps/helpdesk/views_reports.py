"""Ecran de rapports consolide `helpdesk` (HD4, cf. plan section
« Écrans » : « Un ecran de rapports combine (CSAT + performance agents +
conformite SLA), meme patron U5 (\"un ecran de rapports par module, pas un
par indicateur\") »). UN SEUL template (`helpdesk/reports.html`, sections
CSAT/performance agents/benchmarking d'equipe/conformite SLA) — jamais
quatre ecrans separes, cf. garde de tete de chantier sur le budget
d'ecrans (200/215 avant HD4, +1 maximum).

Meme discipline que le reste du module : appelle directement
`services.reports`, jamais l'API ninja interne (cf. `apps.mrp.
views_reports`/`apps.sales.views_reports`)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.core.views.tenant_web import resolve_tenant
from apps.helpdesk.services.reports import (
    agent_performance_report,
    csat_summary,
    sla_compliance_report,
    team_benchmark_report,
)

# Fenetre par defaut quand `date_from`/`date_to` ne sont pas fournis en
# query params — meme choix (30 jours glissants) que documente au plan,
# meme convention de "premier jour du mois" que `apps.mrp.views_reports`/
# `apps.sales.views_reports` n'est PAS reprise ici (une fenetre glissante
# de 30 jours est plus adaptee a un rapport operationnel court terme
# helpdesk qu'un mois calendaire).
_DEFAULT_WINDOW_DAYS = 30


@login_required
def reports_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    today = timezone.now().date()
    date_from = parse_date(request.GET.get("date_from", "")) or (
        today - timezone.timedelta(days=_DEFAULT_WINDOW_DAYS)
    )
    date_to = parse_date(request.GET.get("date_to", "")) or today

    return render(
        request,
        "helpdesk/reports.html",
        {
            "date_from": date_from,
            "date_to": date_to,
            "csat": csat_summary(tenant, date_from=date_from, date_to=date_to),
            "agents": agent_performance_report(tenant, date_from=date_from, date_to=date_to),
            "teams": team_benchmark_report(tenant, date_from=date_from, date_to=date_to),
            "sla": sla_compliance_report(tenant, date_from=date_from, date_to=date_to),
        },
    )
