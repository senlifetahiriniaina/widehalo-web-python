from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.chat.services.public import get_or_create_document_channel
from apps.core.models.audit import AuditLog
from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.core.views.smart_table import Column, smart_table_response
from apps.partners.models import Partner
from apps.partners.services.onboarding import create_partner

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="nif", label="NIF"),
    Column(key="credit_limit_mga", label="Plafond credit (MGA)", searchable=False),
]


@login_required
def partner_list(request: HttpRequest) -> HttpResponse:
    queryset = Partner.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="partners.list",
        columns=COLUMNS,
        queryset=queryset,
        page_template="partners/list.html",
    )


@login_required
def partner_detail(request: HttpRequest, partner_id: str) -> HttpResponse:
    """Bandeau de workflow + panneau lateral (audit / chat / documents),
    composants transversaux reutilisables demontres ici sur l'entite
    partenaire (aucune machine a etats propre a `Partner` dans ce lot — le
    bandeau affiche simplement le statut actif/archive)."""
    partner = get_object_or_404(Partner, id=partner_id)
    content_type = ContentType.objects.get_for_model(Partner)
    # `@login_required` garantit un utilisateur authentifie a l'execution ;
    # ce cast satisfait django-stubs qui type `request.user` en
    # `User | AnonymousUser` par defaut.
    user = cast(User, request.user)

    audit_entries = AuditLog.objects.filter(
        content_type=content_type, object_id=str(partner.id)
    ).order_by("-created_at")[:20]
    documents = Document.objects.filter(content_type=content_type, object_id=str(partner.id))

    uploaded_file = request.FILES.get("document")
    if request.method == "POST" and uploaded_file is not None:
        store_document(
            tenant=partner.tenant,
            uploaded_file=uploaded_file,
            uploaded_by=user if user.is_authenticated else None,
            content_object=partner,
        )
        return redirect("partners:detail", partner_id=partner.id)

    chat_channel_id = get_or_create_document_channel(
        tenant=partner.tenant, content_object=partner, participants=[user], title=partner.name
    )

    return render(
        request,
        "partners/detail.html",
        {
            "partner": partner,
            "audit_entries": audit_entries,
            "documents": documents,
            "chat_channel_id": chat_channel_id,
        },
    )


@login_required
def partner_create_wizard(request: HttpRequest) -> HttpResponse:
    """Assistant multi-etapes (composant transversal) : etape 1 (identite),
    etape 2 (roles + plafond credit) — chaque etape est un fragment HTMX,
    aucune page complete n'est rechargee entre les deux."""
    step = request.GET.get("step") or request.POST.get("step") or "1"

    if request.method == "POST" and step == "2":
        tenant = _resolve_tenant(request)
        try:
            credit_limit = Decimal(request.POST.get("credit_limit_mga") or "0")
        except InvalidOperation:
            credit_limit = Decimal(0)

        partner = create_partner(
            tenant=tenant,
            name=request.session.get("wizard_partner_name", ""),
            roles=request.POST.getlist("roles"),
            nif=request.session.get("wizard_partner_nif", ""),
            credit_limit_mga=credit_limit,
        )
        request.session.pop("wizard_partner_name", None)
        request.session.pop("wizard_partner_nif", None)
        return redirect("partners:detail", partner_id=partner.id)

    if request.method == "POST" and step == "1":
        request.session["wizard_partner_name"] = request.POST.get("name", "")
        request.session["wizard_partner_nif"] = request.POST.get("nif", "")
        return render(request, "partners/wizard_step2.html", {})

    return render(request, "partners/wizard_step1.html", {})


def _resolve_tenant(request: HttpRequest) -> Tenant:
    tenant_id = request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""
    return Tenant.objects.get(id=tenant_id)
