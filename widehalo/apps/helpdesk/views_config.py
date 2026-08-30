"""Ecrans de configuration du module `helpdesk` (HD2+HD3), regroupes sous
le hub "Parametres" (meme convention que `apps.purchase.views_config`/
`apps.accounting.views_config`) : politiques de SLA (`HlpSlaPolicy`),
regles d'escalade (`HlpEscalationRule`) et, depuis HD3, gabarits de
reponse (`HlpResponseTemplate`).

**RBAC** : les 2 permissions SLA/escalade sont PERSONNALISEES et
restreintes a `admin`/`direction` cote API (`helpdesk.manage_hlpslapolicy`/
`manage_hlpescalationrule`, cf. `apps.helpdesk.api`/`apps.core.services.
rbac_policy.CUSTOM_PERMISSIONS_MANAGE_HLP_ROLES`) — l'ecran HTMX lui-meme
ne fait que `@login_required`, meme discipline exacte que `apps.projects.
views_config.config_custom_fields` (le controle N2 fin est applique cote
service/API, pas dans l'ecran).

**HD3 — `HlpResponseTemplate`** : PAS de permission personnalisee (cf.
`apps.helpdesk.api`, section RBAC dediee KB/gabarits) — les permissions
auto-generees standard suffisent (`helpdesk.add_hlpresponsetemplate`
deja accorde a TOUS les 9 roles non admin/direction par la matrice
app-level, `change`/suppression restant `admin`/`direction`)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.views.tenant_web import resolve_tenant
from apps.helpdesk.models import (
    PRIORITY_CHOICES,
    HlpEscalationRule,
    HlpResponseTemplate,
    HlpSlaPolicy,
    HlpTeam,
)


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "helpdesk/config_index.html", {})


@login_required
def config_sla_policies(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            HlpSlaPolicy.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                priority=request.POST.get("priority", ""),
                first_response_minutes=int(request.POST.get("first_response_minutes") or 0),
                resolution_minutes=int(request.POST.get("resolution_minutes") or 0),
                created_by=request.user,
            )
        except (ValidationError, ValueError) as exc:
            error = str(exc)

    policies = HlpSlaPolicy.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "helpdesk/config_sla_policies.html",
        {"policies": policies, "priorities": PRIORITY_CHOICES, "error": error},
    )


@login_required
def config_escalation_rules(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            HlpEscalationRule.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                condition_type=request.POST.get("condition_type", ""),
                threshold_minutes=int(request.POST["threshold_minutes"])
                if request.POST.get("threshold_minutes")
                else None,
                min_priority=request.POST.get("min_priority", ""),
                escalate_to_team_id=request.POST.get("escalate_to_team_id") or None,
                created_by=request.user,
            )
        except (ValidationError, ValueError) as exc:
            error = str(exc)

    rules = HlpEscalationRule.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "helpdesk/config_escalation_rules.html",
        {
            "rules": rules,
            "condition_types": HlpEscalationRule.CONDITION_TYPE_CHOICES,
            "priorities": PRIORITY_CHOICES,
            "teams": HlpTeam.objects.filter(tenant=tenant, is_active=True),
            "error": error,
        },
    )


@login_required
def config_response_templates(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            HlpResponseTemplate.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                category=request.POST.get("category", ""),
                body=request.POST.get("body", ""),
                created_by=request.user,
            )
        except ValidationError as exc:
            error = str(exc)

    templates = HlpResponseTemplate.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "helpdesk/config_response_templates.html",
        {"templates": templates, "error": error},
    )
