"""Ecrans HTMX minimaux du module `helpdesk` (HD1) : liste des tickets
(SmartTable), detail (fil de commentaires + bandeau de transitions FSM +
lien vers l'enregistrement operationnel reference), creation. Meme patron
que `apps.feasibility.views`/`apps.projects.views` : chaque vue appelle
directement les fonctions de service, jamais l'API ninja — `@login_required`
seul au niveau vue, le controle RBAC fin (N2 app-level + N3 scope
requester/assignee) vit dans `apps.helpdesk.api` pour les appelants API ;
ces ecrans HTMX repliquent explicitement le scope N3
(`user_can_manage_ticket`) avant toute transition/commentaire, faute de
passer par la couche API pour ces actions (meme discipline que le reste du
depot : un ecran qui appelle directement les services doit reappliquer lui-
meme les gardes N3 pertinentes).

**Simplification V1 disclosed** : le rattachement generique
(`content_type`/`object_id`) est saisi via un simple champ texte (app_label.
model + UUID), pas un picker de recherche riche — meme si
`ticket_type.related_content_type` est renseigne, l'ecran se contente
d'afficher le type de modele attendu en indication, la recherche/
autocompletion reste hors perimetre HD1."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.helpdesk.models import KIND_CHOICES, PRIORITY_CHOICES, HlpTicket, HlpTicketTypeCatalog
from apps.helpdesk.services.tickets import (
    add_comment,
    assign_ticket,
    cancel_ticket,
    close_ticket,
    create_ticket,
    escalate_ticket,
    reopen_ticket,
    request_more_info,
    resolve_ticket,
    resume_ticket,
    user_can_manage_ticket,
)

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="subject", label="Sujet"),
    Column(key="kind", label="Type", searchable=False),
    Column(key="priority", label="Priorite", searchable=False),
    Column(key="state", label="Statut", searchable=False),
]

_TRANSITIONS = {
    "assign": assign_ticket,
    "request_more_info": request_more_info,
    "resume": resume_ticket,
    "resolve": resolve_ticket,
    "reopen": reopen_ticket,
    "close": close_ticket,
    "escalate": escalate_ticket,
    "cancel": cancel_ticket,
}


@login_required
def ticket_list(request: HttpRequest) -> HttpResponse:
    queryset = HlpTicket.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="helpdesk.tickets",
        columns=COLUMNS,
        queryset=queryset,
        page_template="helpdesk/list.html",
        page_context={"row_url_name": "helpdesk:detail"},
    )


@login_required
def ticket_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None
    if request.method == "POST":
        try:
            ticket_type = None
            ticket_type_id = request.POST.get("ticket_type_id")
            if ticket_type_id:
                ticket_type = get_object_or_404(HlpTicketTypeCatalog, id=ticket_type_id)
            ticket = create_ticket(
                tenant,
                subject=request.POST.get("subject", ""),
                description=request.POST.get("description", ""),
                kind=request.POST.get("kind", ""),
                ticket_type=ticket_type,
                priority=request.POST.get("priority", ""),
                requester=user,
                created_by=user,
            )
            return redirect("helpdesk:detail", ticket_id=ticket.id)
        except ValidationError as exc:
            error = str(exc)
    return render(
        request,
        "helpdesk/create.html",
        {
            "error": error,
            "kinds": KIND_CHOICES,
            "priorities": PRIORITY_CHOICES,
            "ticket_types": HlpTicketTypeCatalog.objects.filter(is_active=True),
        },
    )


@login_required
def ticket_detail(request: HttpRequest, ticket_id: str) -> HttpResponse:
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if not user_can_manage_ticket(ticket, user):
                raise PermissionDenied(
                    "Vous ne pouvez agir que sur vos propres tickets (demandeur ou assigne)."
                )
            if action == "comment":
                add_comment(
                    ticket,
                    author=user,
                    body=request.POST.get("body", ""),
                    is_internal_note=bool(request.POST.get("is_internal_note")),
                )
            elif action in _TRANSITIONS:
                _TRANSITIONS[action](ticket, user)
        except (ValidationError, TransitionPermissionError, PermissionDenied) as exc:
            error = str(exc)

    related_object = None
    related_model_label = ""
    if ticket.ticket_type and ticket.ticket_type.related_content_type_id:
        content_type = ticket.ticket_type.related_content_type
        related_model_label = f"{content_type.app_label}.{content_type.model}"
    if ticket.content_type_id and ticket.object_id:
        related_object = ticket.content_object

    return render(
        request,
        "helpdesk/detail.html",
        {
            "ticket": ticket,
            "error": error,
            "comments": ticket.comments.all(),
            "can_manage": user_can_manage_ticket(ticket, user),
            "related_object": related_object,
            "related_model_label": related_model_label,
        },
    )
