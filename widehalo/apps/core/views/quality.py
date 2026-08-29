"""Ecran generique « Qualite » (QLT1-2) : liste des gabarits de controle,
formulaire de creation d'inspection (choix du gabarit + saisie du resultat
par critere), liste des inspections avec statut passed/failed — rattachable
depuis n'importe quel ecran de detail d'un autre module via le mecanisme
content_type/object_id (l'integration effective dans des ecrans d'autres
modules — ex. un bouton "Lancer une inspection" sur une fiche `StkLot` —
est un travail futur, hors perimetre QLT1-2, meme reserve que RSK1-2)."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.quality import (
    RESULT_STATUS_CHOICES,
    SECTOR_CHOICES,
    QltChecklistTemplate,
    QltInspection,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.quality import create_checklist_template, create_inspection
from apps.core.views.smart_table import Column, smart_table_response

TEMPLATE_COLUMNS = [
    Column(key="name", label="Nom"),
    Column(key="sector_code", label="Secteur"),
]

INSPECTION_COLUMNS = [
    Column(key="template__name", label="Gabarit", searchable=False),
    Column(key="passed", label="Resultat", searchable=False),
    Column(key="inspected_at", label="Date", searchable=False),
]


def _resolve_tenant(request: HttpRequest) -> Tenant:
    tenant_id = request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""
    return Tenant.objects.get(id=tenant_id)


@login_required
def template_list(request: HttpRequest) -> HttpResponse:
    return smart_table_response(
        request,
        table_key="core.qlt_templates",
        columns=TEMPLATE_COLUMNS,
        queryset=QltChecklistTemplate.objects.all(),
        page_template="quality/template_list.html",
    )


@login_required
def template_create(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            error = _("Le nom du gabarit est obligatoire.")
        else:
            codes = request.POST.getlist("item_code")
            labels = request.POST.getlist("item_label")
            expecteds = request.POST.getlist("item_expected")
            items = [
                {"code": code, "label": label, "expected": expected}
                for code, label, expected in zip(codes, labels, expecteds, strict=False)
                if code
            ]
            template = create_checklist_template(
                tenant=_resolve_tenant(request),
                name=name,
                created_by=user,
                sector_code=request.POST.get("sector_code", ""),
                items=items,
            )
            return redirect("qlt_template_detail", template_id=template.id)

    return render(
        request,
        "quality/template_create.html",
        {"error": error, "sector_choices": SECTOR_CHOICES},
    )


@login_required
def template_detail(request: HttpRequest, template_id: str) -> HttpResponse:
    template = get_object_or_404(QltChecklistTemplate, id=template_id)
    return render(request, "quality/template_detail.html", {"template": template})


@login_required
def inspection_list(request: HttpRequest) -> HttpResponse:
    return smart_table_response(
        request,
        table_key="core.qlt_inspections",
        columns=INSPECTION_COLUMNS,
        queryset=QltInspection.objects.select_related("template").all(),
        page_template="quality/inspection_list.html",
    )


@login_required
def inspection_create(request: HttpRequest) -> HttpResponse:
    """Formulaire de saisie d'une inspection : choix d'un `QltChecklistTemplate`
    puis saisie du statut/commentaire pour chacun de ses `items`."""
    user = cast(User, request.user)
    error = None
    template = None
    template_id = request.GET.get("template_id") or request.POST.get("template_id")
    if template_id:
        template = get_object_or_404(QltChecklistTemplate, id=template_id)

    if request.method == "POST" and template is not None:
        codes = request.POST.getlist("result_code")
        statuses = request.POST.getlist("result_status")
        comments = request.POST.getlist("result_comment")
        results = [
            {"code": code, "status": status, "comment": comment}
            for code, status, comment in zip(codes, statuses, comments, strict=False)
        ]
        if not results:
            error = _("Au moins un critere doit etre renseigne.")
        else:
            inspection = create_inspection(
                tenant=_resolve_tenant(request),
                template=template,
                inspector=user,
                results=results,
                inspected_at=timezone.now(),
            )
            return redirect("qlt_inspection_detail", inspection_id=inspection.id)

    return render(
        request,
        "quality/inspection_create.html",
        {
            "error": error,
            "template": template,
            "templates": QltChecklistTemplate.objects.all(),
            "result_status_choices": RESULT_STATUS_CHOICES,
        },
    )


@login_required
def inspection_detail(request: HttpRequest, inspection_id: str) -> HttpResponse:
    inspection = get_object_or_404(
        QltInspection.objects.select_related("template", "inspector"), id=inspection_id
    )
    return render(request, "quality/inspection_detail.html", {"inspection": inspection})
