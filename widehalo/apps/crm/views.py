"""Ecrans HTMX minimaux du module `crm` (U1) : liste des opportunites
(scopee RG-CRM-5), detail avec bandeau d'etape + chronologie des
activites, saisie rapide. Meme patron que `apps.accounting.views`."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models.user import User
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.crm.models import (
    CrmActivity,
    CrmLead,
    CrmLostReason,
    CrmPipeline,
    CrmStage,
    CrmTeam,
)
from apps.crm.services.activities import lead_timeline, log_activity
from apps.crm.services.discounts import DiscountApprovalRequiredError, enforce_discount_threshold
from apps.crm.services.leads import (
    add_lead_line,
    convert_lead_to_partner,
    create_lead_quick,
)
from apps.crm.services.pipeline import move_lead_to_stage
from apps.crm.services.pipelines import resolve_default_pipeline
from apps.crm.services.scoping import scope_leads_for_user
from apps.crm.services.scoring import compute_lead_score, whatsapp_contact_link

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    # `search_key` : `stage` est une FK — la chercher directement levait
    # `FieldError` et rendait 500 des la premiere frappe (L4).
    Column(key="stage", label="Etape", search_key="stage__name"),
    Column(key="expected_revenue_mga", label="Montant attendu (MGA)", searchable=False),
]


@login_required
@screen_permission("crm.view_crmlead")
def lead_list(request: HttpRequest) -> HttpResponse:
    queryset = scope_leads_for_user(CrmLead.objects.filter(is_active=True), request.user)
    return smart_table_response(
        request,
        table_key="crm.leads",
        columns=COLUMNS,
        queryset=queryset,
        page_template="crm/list.html",
        page_context={"row_url_name": "crm:detail"},
    )


def _parse_due_at(raw: str) -> datetime | None:
    """L'echeance saisie par un `<input type="datetime-local">`, ou `None`.

    Le navigateur envoie « 2026-06-30T09:00 » — une heure LOCALE sans
    fuseau. La rendre consciente du fuseau courant plutot que la laisser
    naive : une echeance naive comparee a `timezone.now()` leverait, et la
    tuile « relances en retard » (CRM-4) tombe precisement sur cette
    comparaison.

    Une chaine illisible rend `None` plutot que de lever : une echeance
    mal saisie ne doit pas empecher d'enregistrer l'activite elle-meme —
    l'utilisateur la corrigera, et l'activite existe."""
    if not raw:
        return None
    try:
        naive = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


#: Droit exige par chaque action de la fiche d'opportunite.
_DROITS_OPPORTUNITE = {"log_activity": "crm.add_crmactivity"}


@login_required
@screen_permission("crm.view_crmlead")
def lead_detail(request: HttpRequest, lead_id: str) -> HttpResponse:
    # RG-CRM-5 (CRM-6 du cahier des charges) : correctif d'un manque reel —
    # cette vue recuperait le lead SANS repasser par
    # `scope_leads_for_user`, contrairement a `lead_list` juste au-dessus.
    # Consequence avant ce correctif : n'importe quel utilisateur
    # authentifie du tenant (pas seulement le vendeur assigne ou son
    # equipe) pouvait consulter ET agir (changer d'etape, ajouter une
    # activite/ligne) sur N'IMPORTE QUEL lead par simple connaissance de
    # son UUID. `get_object_or_404` sur le queryset deja scope reproduit le
    # meme comportement "objet inexistant" (404) qu'un ID invalide plutot
    # que de distinguer "n'existe pas" de "existe mais hors portee" —
    # coherent avec le choix deja fait sur les bulletins de paie (RG-PAY-9)
    # de ne jamais laisser deviner l'existence d'un enregistrement d'autrui.
    lead = get_object_or_404(
        scope_leads_for_user(CrmLead.objects.filter(is_active=True), request.user), id=lead_id
    )
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        # `log_activity` CREE une activite ; les trois autres actions
        # MODIFIENT l'opportunite. Les memes codenames que l'API porte sur
        # les operations homologues (`apps/crm/api.py` : `add_crmactivity`
        # pour la creation d'activite, `change_crmlead` pour le reste).
        refus = screen_forbidden(
            request, _DROITS_OPPORTUNITE.get(action or "", "crm.change_crmlead")
        )
        if refus is not None:
            return refus
        try:
            if action == "move_stage":
                stage = get_object_or_404(CrmStage, id=request.POST.get("stage_id"))
                lost_reason_id = request.POST.get("lost_reason_id")
                lost_reason = (
                    get_object_or_404(CrmLostReason, id=lost_reason_id) if lost_reason_id else None
                )
                move_lead_to_stage(
                    lead,
                    stage,
                    lost_reason=lost_reason,
                    comment=request.POST.get("comment", ""),
                    moved_by=user,
                )
            elif action == "convert":
                # CRM-3 : la conversion doit etre ATTEIGNABLE, pas seulement
                # ecrite. Un service de conversion qu'aucun ecran n'appelle
                # serait le meme motif que ceux que ce chantier corrige
                # depuis le debut.
                convert_lead_to_partner(lead)
            elif action == "log_activity":
                # T2 (CRM-7) — `due_at` etait le champ manquant, et avec lui
                # le parcours UC1 tout entier : « opportunite creee,
                # rattachee a une societe, avec une ACTIVITE PLANIFIEE ».
                # Rien dans le produit ne l'ecrivait, sauf le jeu de
                # demonstration.
                due_at_raw = request.POST.get("due_at", "").strip()
                log_activity(
                    lead,
                    activity_type=request.POST.get("activity_type", "call"),
                    subject=request.POST.get("subject", ""),
                    notes=request.POST.get("notes", ""),
                    due_at=_parse_due_at(due_at_raw),
                    assigned_to=user,
                )
            elif action == "add_line":
                variant_id_raw = request.POST.get("variant_id", "").strip()
                unit_price_raw = request.POST.get("unit_price", "").strip()
                line = add_lead_line(
                    lead,
                    description=request.POST.get("description", ""),
                    variant_id=uuid.UUID(variant_id_raw) if variant_id_raw else None,
                    qty=Decimal(request.POST.get("qty") or "1"),
                    unit_price=Decimal(unit_price_raw) if unit_price_raw else None,
                    discount_pct=Decimal(request.POST.get("discount_pct") or "0"),
                    is_custom=bool(request.POST.get("is_custom")),
                )
                enforce_discount_threshold(line, requested_by=user)
        except (
            ValidationError,
            DiscountApprovalRequiredError,
            InvalidOperation,
            ValueError,
        ) as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            return redirect("crm:detail", lead_id=lead.id)

    return render(
        request,
        "crm/detail.html",
        {
            "lead": lead,
            "stages": lead.pipeline.stages.all(),
            "lost_reasons": CrmLostReason.objects.filter(tenant=lead.tenant),
            "activities": lead_timeline(lead),
            # Les CINQ types declares, pas les trois que le gabarit codait
            # en dur — il omettait « relance », le type meme de l'activite
            # qu'UC1 demande de planifier.
            "activity_type_choices": CrmActivity.TYPE_CHOICES,
            "lines": lead.lines.all(),
            "score": compute_lead_score(lead),
            "whatsapp_link": whatsapp_contact_link(lead),
            # L4 (CRM-1) : fil de discussion sur l'opportunite. La garde de
            # perimetre correspondante est enregistree par
            # `services.chatter_registration` — sans elle, le repli par
            # defaut serait la permission de MODELE `crm.view_crmlead`, que
            # tout commercial porte.
            "chatter_app_label": lead._meta.app_label,
            "chatter_model": lead._meta.model_name,
            "chatter_object_id": str(lead.id),
            "error": error,
        },
    )


@login_required
@screen_permission("crm.view_crmlead")
def lead_kanban(request: HttpRequest) -> HttpResponse:
    """CRM-1 — le pipeline en colonnes, avec glisser-deposer.

    **Ce que le critere demandait, et qui n'existait pas.** « Depuis le
    PIPELINE, deplacer une opportunite d'une colonne a l'autre met a jour
    son etape, inscrit la transition dans le chatter et dans le journal
    d'audit, sans rechargement complet de la page. » Le changement d'etape
    se faisait par un `<select>` depuis la FICHE, jamais depuis un
    pipeline — aucun kanban n'existait dans `apps/crm` ni dans
    `templates/crm`, alors que `Sortable.min.js` etait vendorise et
    utilise par `mrp` et `projects`.

    Patron repris tel quel de `mrp.views.work_order_kanban` (colonnes,
    poignee de 44 px, `requestSubmit()` pour rester intercepte par
    `offline_queue.js`), y compris sa DOCTRINE : le glisser-deposer est
    une amelioration cosmetique, le formulaire reste le seul chemin
    accessible au clavier et au lecteur d'ecran — SortableJS n'a aucun
    support clavier natif.

    **Perimetre RG-CRM-5 applique**, comme `lead_list` et `lead_detail` :
    un commercial ne voit dans son pipeline que ses propres opportunites.
    Un kanban qui afficherait tout le pipeline du tenant rouvrirait sur un
    ecran la faille refermee sur l'API aux bloquants (4/4)."""
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "crm.change_crmlead")
        if refus is not None:
            return refus

    if request.method == "POST":
        lead = get_object_or_404(
            scope_leads_for_user(CrmLead.objects.filter(is_active=True), user),
            id=request.POST.get("lead_id"),
        )
        stage = get_object_or_404(CrmStage, id=request.POST.get("stage_id"))
        lost_reason_id = request.POST.get("lost_reason_id")
        lost_reason = (
            get_object_or_404(CrmLostReason, id=lost_reason_id) if lost_reason_id else None
        )
        try:
            move_lead_to_stage(
                lead,
                stage,
                lost_reason=lost_reason,
                comment=request.POST.get("comment", ""),
                moved_by=user,
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            return redirect("crm:kanban")

    leads = (
        scope_leads_for_user(CrmLead.objects.filter(is_active=True), user)
        .select_related("stage", "pipeline")
        .order_by("-expected_revenue_mga")
    )
    pipeline = resolve_default_pipeline(resolve_tenant(request))
    stages = list(pipeline.stages.order_by("sequence")) if pipeline is not None else []

    cards_by_stage: dict[str, list[CrmLead]] = {}
    for lead in leads:
        cards_by_stage.setdefault(str(lead.stage_id), []).append(lead)

    # Chaque colonne connait l'etape SUIVANTE : c'est elle qui rend le
    # depot legal (meme regle que `mrp`, ou seul un depot vers la colonne
    # n+1 soumet le formulaire). Une opportunite ne saute pas d'etape.
    columns = []
    for index, stage in enumerate(stages):
        next_stage = stages[index + 1] if index + 1 < len(stages) else None
        columns.append(
            {
                "stage": stage,
                "next_stage": next_stage,
                "cards": cards_by_stage.get(str(stage.id), []),
            }
        )

    return render(
        request,
        "crm/kanban.html",
        {
            "columns": columns,
            "lost_reasons": CrmLostReason.objects.all(),
            "has_pipeline": pipeline is not None,
            "error": error,
        },
    )


@login_required
@screen_permission("crm.view_crmlead")
def lead_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "crm.add_crmlead")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            partner_id_raw = request.POST.get("partner_id", "").strip()
            pipeline_id_raw = request.POST.get("pipeline", "").strip()
            team_id_raw = request.POST.get("team", "").strip()
            revenue_raw = request.POST.get("expected_revenue_mga", "").strip()
            close_date_raw = request.POST.get("expected_close_date", "").strip()
            priority = request.POST.get("priority", "").strip()

            extra: dict[str, object] = {}
            if team_id_raw:
                extra["team_id"] = uuid.UUID(team_id_raw)
            if revenue_raw:
                extra["expected_revenue_mga"] = Decimal(revenue_raw)
            if close_date_raw:
                extra["expected_close_date"] = date.fromisoformat(close_date_raw)
            if priority:
                extra["priority"] = priority
            for field in ("source", "contact_name", "email", "phone", "description"):
                value = request.POST.get(field, "").strip()
                if value:
                    extra[field] = value

            pipeline = (
                get_object_or_404(CrmPipeline, id=pipeline_id_raw) if pipeline_id_raw else None
            )

            lead = create_lead_quick(
                tenant=tenant,
                name=request.POST.get("name", ""),
                partner_id=uuid.UUID(partner_id_raw) if partner_id_raw else None,
                pipeline=pipeline,
                salesperson=request.user,
                **extra,
            )
        except (ValueError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("crm:detail", lead_id=lead.id)

    default_pipeline = resolve_default_pipeline(tenant)
    return render(
        request,
        "crm/create.html",
        {
            "error": error,
            "pipelines": CrmPipeline.objects.filter(tenant=tenant),
            "default_pipeline_id": default_pipeline.id if default_pipeline else None,
            "teams": CrmTeam.objects.filter(tenant=tenant),
            "priority_choices": CrmLead.PRIORITY_CHOICES,
        },
    )
