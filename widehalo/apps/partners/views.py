from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.chat.services.public import get_or_create_document_channel
from apps.core.models.audit import AuditLog
from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.core.views.smart_table import Column, smart_table_response
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.merge import merge_partners
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
def partner_edit(request: HttpRequest, partner_id: str) -> HttpResponse:
    """Formulaire d'edition simple : aucun service dedie n'existe pour la
    mise a jour (seul `create_partner` existe cote onboarding), donc on suit
    le patron deja utilise ailleurs (ex. `apps.accounting.views`) —
    `full_clean()` + `save()` sur l'instance recuperee, entoure d'un
    try/except `ValidationError`."""
    partner = get_object_or_404(Partner, id=partner_id)
    error = None

    if request.method == "POST":
        partner.name = request.POST.get("name", partner.name)
        partner.nif = request.POST.get("nif", "")
        partner.roles = request.POST.getlist("roles")
        try:
            partner.credit_limit_mga = Decimal(request.POST.get("credit_limit_mga") or "0")
        except InvalidOperation:
            error = _("Plafond crédit invalide.")
        else:
            try:
                partner.full_clean()
                partner.save()
            except ValidationError as exc:
                error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            else:
                return redirect("partners:detail", partner_id=partner.id)

    return render(
        request,
        "partners/edit.html",
        {"partner": partner, "error": error, "role_choices": Partner.ROLE_CHOICES},
    )


@login_required
def duplicate_alert_list(request: HttpRequest) -> HttpResponse:
    """Liste des alertes de doublon non resolues du tenant courant, avec une
    action « Resoudre » (marque simplement `resolved_at`) et un lien direct
    vers l'ecran de fusion prerempli pour la paire concernee."""
    if request.method == "POST":
        alert = get_object_or_404(DuplicateAlert, id=request.POST.get("alert_id"))
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["resolved_at"])
        return redirect("partners:duplicates")

    alerts = DuplicateAlert.objects.filter(resolved_at__isnull=True).select_related(
        "partner", "duplicate_of"
    )
    return render(request, "partners/duplicates.html", {"alerts": alerts})


@login_required
def partner_merge(request: HttpRequest) -> HttpResponse:
    """Choix d'un partenaire primaire et d'un doublon (deux listes, ou
    prerempli via `?primary=<id>&duplicate=<id>` depuis une alerte), puis
    appel a `merge_partners()`. Toute `DuplicateAlert` ouverte reliant les
    deux partenaires (dans un sens ou l'autre) est resolue au passage."""
    error = None
    partners = Partner.objects.filter(is_active=True).order_by("name")
    primary_id = request.POST.get("primary_id") or request.GET.get("primary") or ""
    duplicate_id = request.POST.get("duplicate_id") or request.GET.get("duplicate") or ""

    if request.method == "POST":
        try:
            if not primary_id or not duplicate_id:
                raise ValidationError(_("Sélectionnez les deux partenaires a fusionner."))
            if primary_id == duplicate_id:
                raise ValidationError(_("Le partenaire primaire et le doublon doivent différer."))
            primary = get_object_or_404(Partner, id=primary_id)
            duplicate = get_object_or_404(Partner, id=duplicate_id)
            merge_partners(primary=primary, duplicate=duplicate)
        except ValidationError as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            # `merge_partners()` reassigne deja, par introspection generique
            # des FK, les `DuplicateAlert.partner`/`duplicate_of` qui
            # pointaient vers `duplicate` afin qu'ils pointent vers
            # `primary` — toute alerte encore ouverte impliquant `primary`
            # concerne donc necessairement la paire qui vient d'etre fusionnee.
            related_alerts = DuplicateAlert.objects.filter(resolved_at__isnull=True).filter(
                models.Q(partner=primary) | models.Q(duplicate_of=primary)
            )
            for related_alert in related_alerts:
                related_alert.resolved_at = timezone.now()
                related_alert.save(update_fields=["resolved_at"])
            return redirect("partners:detail", partner_id=primary.id)

    return render(
        request,
        "partners/merge.html",
        {
            "partners": partners,
            "primary_id": primary_id,
            "duplicate_id": duplicate_id,
            "error": error,
        },
    )


@login_required
def partner_create_wizard(request: HttpRequest) -> HttpResponse:
    """Assistant multi-etapes (composant transversal) : etape 1 (identite),
    etape 2 (roles + plafond credit) — chaque etape est un fragment HTMX,
    aucune page complete n'est rechargee entre les deux.

    **Mode `?embed=1` (UXR3)** : consomme par `components/_partner_picker.html`
    quand l'assistant est ouvert dans une `whModal()` plutot que sur sa
    propre page. Les deux etapes rendent alors des fragments nus (jamais
    `{% extends "base.html" %}`) et, a l'issue de l'etape 2, la vue ne
    redirige plus vers `partners:detail` — elle repond par un corps vide
    portant un en-tete `HX-Trigger: wh-partner-created` (id + nom du
    partenaire cree), evenement DOM ecoute par `static/js/ui_patterns.js`
    pour peupler le champ cache/le texte affiche du picker appelant puis
    fermer la modale (`whModal.hide()`). Le flag `embed` transite via le
    query string du `hx-post` du formulaire d'etape 1 (lui-meme regenere
    a l'etape 1 selon que la requete initiale portait `?embed=1`), donc
    aucun etat de session supplementaire n'est necessaire pour le porter
    jusqu'a l'etape 2."""
    step = request.GET.get("step") or request.POST.get("step") or "1"
    embed = request.GET.get("embed") == "1" or request.POST.get("embed") == "1"

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

        if embed:
            response = HttpResponse("")
            response["HX-Trigger"] = json.dumps(
                {
                    "wh-partner-created": {
                        "partner_id": str(partner.id),
                        "partner_name": partner.name,
                    }
                }
            )
            return response
        # Ce POST est declenche par le `hx-post`/`hx-target="#wizard-container"`
        # du formulaire d'etape 1, toujours actif a l'etape 2. Une redirection
        # Django classique (302 + `Location`) serait suivie par htmx AU SEIN
        # de la meme requete AJAX, injectant la page complete de la fiche
        # detail (elle-meme `{% extends "base.html" %}`) dans
        # `#wizard-container` — une coquille (sidebar/topbar) imbriquee dans
        # celle deja affichee. `HX-Redirect` force au contraire une vraie
        # navigation du navigateur, meme patron deja utilise par
        # `apps.chat.views` pour la creation de conversation.
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("partners:detail", args=[partner.id])
        return response

    if request.method == "POST" and step == "1":
        request.session["wizard_partner_name"] = request.POST.get("name", "")
        request.session["wizard_partner_nif"] = request.POST.get("nif", "")
        return render(request, "partners/wizard_step2.html", {})

    if embed:
        return render(request, "partners/_wizard_step1_embed.html", {"embed": True})
    return render(request, "partners/wizard_step1.html", {})


@login_required
def partner_instant_picker(request: HttpRequest) -> HttpResponse:
    """Endpoint leger de recherche instantanee (fragment HTML), consomme
    par `components/_partner_picker.html` (UXR3) — futurs consommateurs :
    creation d'opportunite CRM (UXR4), devis/commandes de vente (UXR5).

    Tenant-scope automatiquement via `Partner.objects` (`TenantManager`,
    cf. `apps/core/models/base.py`) : aucun filtre `tenant=` explicite
    necessaire ni possible a contourner depuis la query string."""
    query = request.GET.get("q", "")
    partners = Partner.objects.filter(is_active=True, name__icontains=query).order_by("name")[:20]
    return render(request, "partners/_instant_picker_results.html", {"partners": partners})


def _resolve_tenant(request: HttpRequest) -> Tenant:
    tenant_id = request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""
    return Tenant.objects.get(id=tenant_id)
