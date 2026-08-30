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
autocompletion reste hors perimetre HD1.

**HD3** ajoute : les ecrans KB (`kb_list`/`kb_create`/`kb_detail`, meme
patron `@login_required` + appel direct aux services que ci-dessus, PAS
la couche API), la suggestion de reponse IA en fragment HTMX
(`ticket_suggest_reply`), et le chat interne integre au detail ticket.

**Integration chat interne (decision disclosed)** : reutilise
`apps.chat.services.public.get_or_create_document_channel` exactement
comme le PREMIER precedent de ce depot pour cette meme integration
(`apps.partners.views.partner_detail`, cf. son import identique) — le
canal est cree/retrouve a chaque GET du detail (idempotent par
construction, cf. docstring de la fonction), puis l'ecran affiche un
simple LIEN `/chat/{channel_id}/` vers l'ecran de messagerie deja
route de l'app `chat` (`chat:channel`, cf. `apps.chat.urls`) — PAS un
widget de chat embarque/HTMX poll sur CETTE page : `chat` expose deja son
propre ecran complet (fil de messages + polling HTMX 10s + formulaire
d'envoi, cf. `apps.chat.views.chat_home`), le dupliquer ici aurait ete une
reinvention sans valeur ajoutee. Meme forme exacte que `partners/
detail.html` (`<a href="/chat/{{ chat_channel_id }}/">`)."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.chat.services.public import get_or_create_document_channel
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.helpdesk.models import (
    KIND_CHOICES,
    PRIORITY_CHOICES,
    HlpKbArticle,
    HlpKbCategory,
    HlpTicket,
    HlpTicketTypeCatalog,
)
from apps.helpdesk.services import kb
from apps.helpdesk.services.ai_assist import suggest_reply
from apps.helpdesk.services.csat import submit_csat_response
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
            if action == "csat":
                # Scope DISTINCT de `user_can_manage_ticket` (cf.
                # `_can_submit_csat` ci-dessous) : le gestionnaire n'est PAS
                # forcement le demandeur, la garde generale ci-dessus ne
                # s'applique donc pas a cette action.
                if not _can_submit_csat(ticket, user):
                    raise PermissionDenied(
                        "Seul le demandeur (ou un gestionnaire) peut repondre a l'enquete."
                    )
                submit_csat_response(
                    ticket,
                    score=int(request.POST.get("score") or 0),
                    comment=request.POST.get("comment", ""),
                )
            else:
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
        except (ValidationError, TransitionPermissionError, PermissionDenied, ValueError) as exc:
            error = str(exc)

    related_object = None
    related_model_label = ""
    if ticket.ticket_type and ticket.ticket_type.related_content_type_id:
        content_type = ticket.ticket_type.related_content_type
        related_model_label = f"{content_type.app_label}.{content_type.model}"
    if ticket.content_type_id and ticket.object_id:
        related_object = ticket.content_object

    # `participants` est type `list[User]` (cf. signature publique) : ne
    # JAMAIS y inclure `None` — `assignee` est filtre explicitement (peut
    # etre non affecte). Cree/retrouve le MEME canal a chaque GET
    # (idempotent par `content_object`, cf. docstring de tete de module).
    participants = [ticket.requester]
    if ticket.assignee is not None:
        participants.append(ticket.assignee)
    chat_channel_id = get_or_create_document_channel(
        tenant=ticket.tenant,
        content_object=ticket,
        participants=participants,
        title=ticket.subject,
    )

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
            "chat_channel_id": chat_channel_id,
            "csat_response": getattr(ticket, "csat_response", None),
            "can_submit_csat": (
                ticket.state in (HlpTicket.STATE_RESOLVED, HlpTicket.STATE_CLOSED)
                and _can_submit_csat(ticket, user)
            ),
        },
    )


def _can_submit_csat(ticket: HlpTicket, user: User) -> bool:
    """Scope DEDIE a la soumission CSAT (cf. `apps.helpdesk.api`, meme
    duplication VOLONTAIRE et disclosed que `_can_manage_kb_article`
    ci-dessous — les ecrans HTMX reappliquent localement les gardes N3
    pertinentes, cf. docstring de tete de module) : le DEMANDEUR
    uniquement (ou un gestionnaire `helpdesk.change_hlpticket`), JAMAIS
    l'assigne seul — noter sa propre resolution viderait l'enquete de son
    sens."""
    if user.has_perm("helpdesk.change_hlpticket"):
        return True
    return ticket.requester_id == user.id


@login_required
def ticket_suggest_reply(request: HttpRequest, ticket_id: str) -> HttpResponse:
    """Fragment HTMX (cf. `templates/helpdesk/_suggest_reply.html`) —
    appele par le bouton « Suggestion IA » du detail ticket. Ne renvoie
    JAMAIS d'erreur serveur : `suggest_reply()` degrade proprement vers une
    chaine vide en toute circonstance (fournisseur non configure, budget
    epuise, ou echec du connecteur reel), affichee ici comme un message
    clair plutot qu'une absence silencieuse."""
    ticket = get_object_or_404(HlpTicket, id=ticket_id)
    suggestion = suggest_reply(ticket, tenant=ticket.tenant)
    return render(request, "helpdesk/_suggest_reply.html", {"suggestion": suggestion})


@login_required
def kb_list(request: HttpRequest) -> HttpResponse:
    """Liste simple (pas de `SmartTable`, disclosed) : une base de
    connaissances se parcourt d'abord par recherche titre/corps, pas par
    tri/pagination de grille de gestion — meme raisonnement que les ecrans
    `config_*` de `views_config.py` (liste + formulaire de creation sur la
    meme page), ici separee en deux ecrans (`kb_list`/`kb_create`) pour ne
    pas noyer la recherche sous un formulaire de creation."""
    tenant = resolve_tenant(request)
    query = request.GET.get("q", "")
    articles = kb.search_articles(tenant, query)
    return render(request, "helpdesk/kb_list.html", {"articles": articles, "query": query})


@login_required
def kb_detail(request: HttpRequest, article_id: str) -> HttpResponse:
    article = get_object_or_404(HlpKbArticle, id=article_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "feedback":
            kb.record_article_feedback(article, helpful=request.POST.get("helpful") == "1")
        elif action == "publish" and _can_manage_kb_article(article, user):
            kb.publish_article(article)
        elif action == "unpublish" and _can_manage_kb_article(article, user):
            kb.unpublish_article(article)
        else:
            error = "Action non autorisee."
        article.refresh_from_db()

    article = kb.record_article_view(article)
    return render(
        request,
        "helpdesk/kb_detail.html",
        {
            "article": article,
            "error": error,
            "can_manage": _can_manage_kb_article(article, user),
        },
    )


def _can_manage_kb_article(article: HlpKbArticle, user: User) -> bool:
    """Scope N3 symetrique a `user_can_manage_ticket` (cf. `services.
    tickets`) : un utilisateur sans `helpdesk.change_hlpkbarticle` peut
    neanmoins publier/depublier/modifier SON PROPRE article — jamais celui
    d'un tiers. Disclosed en detail dans `apps.helpdesk.api`."""
    if user.has_perm("helpdesk.change_hlpkbarticle"):
        return True
    return article.author_id == user.id


@login_required
def kb_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None
    if request.method == "POST":
        try:
            category = None
            category_id = request.POST.get("category_id")
            if category_id:
                category = get_object_or_404(HlpKbCategory, id=category_id)
            article = kb.create_article(
                tenant,
                title=request.POST.get("title", ""),
                body=request.POST.get("body", ""),
                category=category,
                author=user,
                is_published=bool(request.POST.get("is_published")),
                created_by=user,
            )
            return redirect("helpdesk:kb_detail", article_id=article.id)
        except ValidationError as exc:
            error = str(exc)
    return render(
        request,
        "helpdesk/kb_create.html",
        {"error": error, "categories": HlpKbCategory.objects.filter(is_active=True)},
    )
