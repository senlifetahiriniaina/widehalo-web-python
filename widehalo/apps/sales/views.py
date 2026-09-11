"""Ecrans HTMX minimaux du module `sales` (§5.5.7 restant, S7) : liste
devis/commandes (SmartTable), fiches detail avec bandeau de workflow
(boutons d'action), formulaires de creation, conversion devis->commande.
Meme patron que `apps.mrp.views` (session-authentifie, appel direct aux
`services/*`, jamais l'API JWT interne)."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _

from apps.accounting.services.public import list_payment_terms
from apps.catalog.services.public import (
    get_variant_reference,
    is_variant_sellable,
    list_sellable_variants,
)
from apps.core.identifiers import parse_optional_uuid, parse_uuid
from apps.core.models.user import User
from apps.core.services.next_steps import next_steps_for
from apps.core.services.permissions import screen_forbidden, screen_permission, user_role_codes
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.presentation import presentation_response
from apps.core.views.smart_table import Column
from apps.core.views.tenant_web import resolve_tenant
from apps.flows.services.public import document_exchange_panel
from apps.partners.services.public import get_partner_display_names
from apps.sales.models import SalesOrder, SalesQuotation
from apps.sales.services.flow_schema_registration import DOCUMENT_ORDER, DOCUMENT_QUOTATION
from apps.sales.services.invoicing import invoice_order
from apps.sales.services.orders import (
    add_order_line,
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    create_order_from_quotation,
    mark_delivered,
    send_order,
    start_preparation,
    unblock_order,
)
from apps.sales.services.quotations import (
    accept_quotation,
    add_quotation_line,
    create_quotation,
    decline_quotation,
    send_quotation,
)
from apps.sales.services.reports import MARGIN_VISIBLE_ROLES


# RG-SAL-5 : roles autorises a voir `margin_pct` en ecran — meme ensemble
# que `apps.core.services.permissions.SENSITIVE_FIELDS["sales.SalesOrderLine"]`.
# Choix documente (cf. plan/RG-SAL-5) : verification directe des roles de
# session plutot qu'un aller-retour par `filter_fields_for_role` (qui
# masque des CLES de dict, pas des colonnes de gabarit HTML) — le gabarit
# a simplement besoin d'un booleen "affiche la colonne Marge ou non".
def _can_see_margin(user: User) -> bool:
    return bool(user_role_codes(user) & MARGIN_VISIBLE_ROLES)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _enrichir_partenaires(objets: list[Any]) -> None:
    """Resout le nom des tiers des lignes rendues, EN UNE REQUETE.

    **Ce que l'exploitant voyait avant.** La colonne « Partenaire » rendait
    `partner_id`, c'est-a-dire un UUID — et comme ce sont des UUIDv7,
    prefixes par un horodatage, deux commandes du meme jour affichaient les
    memes quatorze premiers caracteres : la colonne ne distinguait rien.

    `partner_id` est un `UUIDField`, jamais une cle etrangere : la regle de
    couplage n°1 interdit a `sales` de connaitre le modele `Partner`. Le nom
    passe donc par la surface publique de `partners`, et EN LOT — un appel
    par ligne couterait vingt-cinq requetes par page."""
    noms = get_partner_display_names({objet.partner_id for objet in objets})
    for objet in objets:
        objet.partner_display = noms.get(str(objet.partner_id), "")


QUOTATION_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    # `amount_total` est exprime dans la DEVISE DU DOCUMENT, jamais
    # forcement en ariary : le mettre en chasse fixe sous un libelle « Ar »
    # mentirait sur un devis en euros. La liste montre donc le converti,
    # comme celle des commandes ; la fiche continue de porter les deux.
    Column(key="amount_total_mga", label="Montant (MGA)", format="mga", searchable=False),
]

ORDER_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="partner_display", label="Partenaire", searchable=False),
    Column(key="salesperson", label="Commercial", searchable=False),
    Column(key="amount_total_mga", label="Montant (MGA)", format="mga", searchable=False),
]


@login_required
@screen_permission("sales.view_salesquotation")
def quotation_list(request: HttpRequest) -> HttpResponse:
    queryset = SalesQuotation.objects.filter(is_active=True)
    return presentation_response(
        request,
        table_key="sales.quotations",
        model_label="sales.SalesQuotation",
        columns=QUOTATION_COLUMNS,
        queryset=queryset,
        page_template="sales/quotation_list.html",
        page_context={"row_url_name": "sales:quotation_detail"},
    )


def _resolve_line(variant_id_raw: str, description_raw: str) -> dict[str, Any]:
    """Une ligne de devis/commande vient soit d'un produit CATALOGUE
    (`variant_id` pose), soit d'une ligne hors catalogue (`is_custom`).
    Cote serveur, un `variant_id` n'est JAMAIS accepte tel quel — revalide
    contre `catalog.services.public.is_variant_sellable` avant de creer la
    ligne (le filtrage du selecteur cote ecran reste contournable par un
    POST direct).

    Parametre plutot qu'appele directement sur `request.POST` (DT6,
    chantier "lignes multiples en un seul POST") : reutilise a l'identique
    par `_resolve_line_from_post` (action `add_line` deja existante de
    l'ecran de detail, comportement inchange) **et** par
    `_parse_lines_from_post` (nouveau parseur multi-lignes des ecrans de
    creation) — la seule difference entre les deux appelants est D'OU
    viennent `variant_id_raw`/`description_raw` (champs `variant_id`/
    `description` uniques vs. champs indexes `variant_id_{i}`/
    `description_{i}`)."""
    variant_id_raw = (variant_id_raw or "").strip()
    if variant_id_raw:
        variant_id = parse_uuid(variant_id_raw, champ=_("produit"))
        if not is_variant_sellable(variant_id):
            raise ValidationError(_("Ce produit n'est pas vendable."))
        description = description_raw or get_variant_reference(variant_id)
        return {"variant_id": variant_id, "description": description, "is_custom": False}
    return {"description": description_raw or "", "is_custom": True}


def _resolve_line_from_post(post) -> dict[str, Any]:
    return _resolve_line(post.get("variant_id") or "", post.get("description") or "")


def _parse_optional_uuid(raw: str) -> uuid.UUID | None:
    """T4bis — délègue à `core.identifiers`, qui refuse par un 400 nommant
    le champ au lieu de laisser `ValueError` remonter en 500."""
    return parse_optional_uuid(raw, champ=_("identifiant"))


def _parse_lines_from_post(post) -> list[dict[str, Any]]:
    """DT6 : lignes multiples en un seul POST — champs a noms indexes
    (`variant_id_0`, `description_0`, `qty_0`, `unit_price_0`, ... `_1`,
    `_2`...) plutot qu'un formset Django (aucun precedent dans ce depot) ou
    un blob JSON cache (les noms indexes restent lisibles ici avec une
    simple boucle `while`, sans dependance a `json.loads`). Boucle tant que
    `variant_id_{i}` OU `description_{i}` est present dans le POST (une
    ligne peut n'avoir que l'un des deux selon catalogue/hors catalogue),
    ignore silencieusement toute ligne entierement vide (aucune ligne
    n'est obligatoire sur ces ecrans de creation) — `sequence` attribue
    dans l'ordre des lignes reellement retenues (jamais l'index `i` brut,
    qui compterait aussi les lignes vides ignorees)."""
    lines: list[dict[str, Any]] = []
    i = 0
    while f"variant_id_{i}" in post or f"description_{i}" in post:
        variant_id_raw = post.get(f"variant_id_{i}", "")
        description_raw = post.get(f"description_{i}", "")
        if not variant_id_raw.strip() and not description_raw.strip():
            i += 1
            continue
        qty_raw = (post.get(f"qty_{i}", "") or "").strip()
        unit_price_raw = (post.get(f"unit_price_{i}", "") or "").strip()
        line = _resolve_line(variant_id_raw, description_raw)
        line["qty"] = Decimal(qty_raw) if qty_raw else Decimal(1)
        line["unit_price"] = Decimal(unit_price_raw) if unit_price_raw else None
        line["sequence"] = len(lines)
        lines.append(line)
        i += 1
    return lines


@login_required
# Un ecran dont la SEULE raison d'etre est la creation exige le droit de
# creer pour s'ouvrir, et pas seulement pour se soumettre : laisser un
# role en lecture seule remplir un formulaire pour le refuser a l'envoi
# lui fait perdre sa saisie et ne lui apprend rien plus tot.
@screen_permission("sales.add_salesquotation")
def quotation_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "sales.add_salesquotation")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            with transaction.atomic():
                quotation = create_quotation(
                    tenant=tenant,
                    partner_id=parse_uuid(request.POST.get("partner_id"), champ=_("client")),
                    date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                    salesperson=user,
                    contact=request.POST.get("contact", ""),
                    reference=request.POST.get("reference", ""),
                    payment_term_id=_parse_optional_uuid(request.POST.get("payment_term_id", "")),
                    incoterm=request.POST.get("incoterm", ""),
                )
                for line in _parse_lines_from_post(request.POST):
                    add_quotation_line(quotation, **line)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:quotation_detail", quotation_id=quotation.id)

    return render(
        request,
        "sales/quotation_create.html",
        {
            "error": error,
            "payment_terms": list_payment_terms(tenant),
            "sellable_variants": list_sellable_variants(),
            "incoterm_choices": SalesQuotation.INCOTERM_CHOICES,
        },
    )


_QUOTATION_ACTIONS = {
    "send": lambda quotation, _post: send_quotation(quotation),
    "accept": lambda quotation, _post: accept_quotation(quotation),
    "decline": lambda quotation, post: decline_quotation(quotation, reason=post.get("reason", "")),
}


@login_required
@screen_permission("sales.view_salesquotation")
def quotation_detail(request: HttpRequest, quotation_id: str) -> HttpResponse:
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    _enrichir_partenaires([quotation])
    user = cast(User, request.user)
    error = None
    new_order = None

    if request.method == "POST":
        refus = screen_forbidden(request, "sales.change_salesquotation")
        if refus is not None:
            return refus

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_quotation_line(
                    quotation,
                    qty=Decimal(post.get("qty") or "1"),
                    unit_price=Decimal(post.get("unit_price")) if post.get("unit_price") else None,
                    sequence=quotation.lines.count(),
                    **_resolve_line_from_post(post),
                )
            elif action == "convert_to_order":
                new_order = create_order_from_quotation(quotation)
            else:
                handler = _QUOTATION_ACTIONS.get(action)
                if handler is not None:
                    handler(quotation, post)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            if new_order is not None:
                return redirect("sales:order_detail", order_id=new_order.id)
            return redirect("sales:quotation_detail", quotation_id=quotation.id)

    return render(
        request,
        "sales/quotation_detail.html",
        {
            "next_steps": next_steps_for(quotation, user),
            "quotation": quotation,
            "lines": quotation.lines.all(),
            "can_see_margin": _can_see_margin(user),
            "sellable_variants": list_sellable_variants(),
            "error": error,
            # T8 (CON-1) — « depuis TOUTE pièce métier ». Le devis est une
            # pièce liable déclarée depuis T0 : il peut partir chez un tiers
            # comme une facture, et il n'a aucun état fiscal — c'est
            # pourquoi le fragment de T4 n'était pas réutilisable ici.
            **document_exchange_panel(
                quotation.tenant, document_type=DOCUMENT_QUOTATION, document_id=quotation.id
            ),
        },
    )


@login_required
@screen_permission("sales.view_salesorder")
def order_list(request: HttpRequest) -> HttpResponse:
    queryset = SalesOrder.objects.filter(is_active=True)
    state = request.GET.get("state")
    partner_id = request.GET.get("partner_id")
    salesperson_id = request.GET.get("salesperson_id")
    if state:
        queryset = queryset.filter(state=state)
    if partner_id:
        queryset = queryset.filter(partner_id=partner_id)
    if salesperson_id:
        queryset = queryset.filter(salesperson_id=salesperson_id)
    return presentation_response(
        request,
        table_key="sales.orders",
        model_label="sales.SalesOrder",
        columns=ORDER_COLUMNS,
        queryset=queryset,
        page_template="sales/order_list.html",
        page_context={
            "row_url_name": "sales:order_detail",
            "state_choices": SalesOrder.STATE_CHOICES,
            "selected_state": state or "",
        },
        enrichir=_enrichir_partenaires,
    )


@login_required
# Un ecran dont la SEULE raison d'etre est la creation exige le droit de
# creer pour s'ouvrir, et pas seulement pour se soumettre : laisser un
# role en lecture seule remplir un formulaire pour le refuser a l'envoi
# lui fait perdre sa saisie et ne lui apprend rien plus tot.
@screen_permission("sales.add_salesorder")
def order_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "sales.add_salesorder")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            with transaction.atomic():
                order = create_order(
                    tenant=tenant,
                    partner_id=parse_uuid(request.POST.get("partner_id"), champ=_("client")),
                    date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                    salesperson=user,
                    contact=request.POST.get("contact", ""),
                    reference=request.POST.get("reference", ""),
                    payment_term_id=_parse_optional_uuid(request.POST.get("payment_term_id", "")),
                    is_export=bool(request.POST.get("is_export")),
                    incoterm=request.POST.get("incoterm", ""),
                )
                for line in _parse_lines_from_post(request.POST):
                    add_order_line(order, **line)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:order_detail", order_id=order.id)

    return render(
        request,
        "sales/order_create.html",
        {
            "error": error,
            "payment_terms": list_payment_terms(tenant),
            "sellable_variants": list_sellable_variants(),
            "incoterm_choices": SalesOrder.INCOTERM_CHOICES,
        },
    )


_ORDER_ACTIONS = {
    "send": lambda order, user, _post: send_order(order, user),
    "confirm": lambda order, user, _post: confirm_order(order, user),
    "unblock": lambda order, user, _post: unblock_order(order, user),
    "start_preparation": lambda order, user, _post: start_preparation(order, user),
    "deliver_partial": lambda order, user, _post: mark_delivered(order, user, partial=True),
    "deliver_full": lambda order, user, _post: mark_delivered(order, user, partial=False),
    "close": lambda order, user, _post: close_order(order, user),
    "cancel": lambda order, user, post: cancel_order(order, user, reason=post.get("reason", "")),
}


@login_required
@screen_permission("sales.view_salesorder")
def order_detail(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(SalesOrder, id=order_id)
    _enrichir_partenaires([order])
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "sales.change_salesorder")
        if refus is not None:
            return refus

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_order_line(
                    order,
                    qty=Decimal(post.get("qty") or "1"),
                    unit_price=Decimal(post.get("unit_price")) if post.get("unit_price") else None,
                    billing_policy=post.get("billing_policy", "on_ordered_qty"),
                    sequence=order.lines.count(),
                    **_resolve_line_from_post(post),
                )
            elif action == "invoice":
                # `invoice_order` rend `None` — sans lever — quand la
                # configuration comptable du tenant est incomplete (aucun
                # journal de vente, aucune periode ouverte, aucun compte de
                # creance). Sa propre docstring l'ecrit : « l'appelant doit
                # traduire ce `None` en configuration comptable manquante,
                # PAS en succes silencieux »
                # (`apps/sales/services/invoicing.py:130-132`). L'ecran
                # l'ignorait : l'exploitant cliquait « Facturer », etait
                # redirige, et rien ne se passait — ni facture, ni message.
                # Trouve par le parcours de bout en bout du bandeau, pas
                # par la relecture.
                if invoice_order(order, user) is None:
                    raise ValidationError(
                        _(
                            "Facturation impossible : la configuration comptable est "
                            "incomplète (journal de vente, période ouverte, comptes de "
                            "créance et de produit)."
                        )
                    )
            else:
                handler = _ORDER_ACTIONS.get(action)
                if handler is not None:
                    handler(order, user, post)
        except (
            ValidationError,
            InvalidOperation,
            ValueError,
            TransitionPermissionError,
        ) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:order_detail", order_id=order.id)

    return render(
        request,
        "sales/order_detail.html",
        {
            "next_steps": next_steps_for(order, user),
            "order": order,
            "lines": order.lines.all(),
            "can_see_margin": _can_see_margin(user),
            "sellable_variants": list_sellable_variants(),
            "error": error,
            # T8 (CON-1) — « depuis TOUTE pièce métier ». Une commande de
            # vente part chez la boutique (T7) comme une facture part chez
            # l'administration ; elle n'a en revanche aucun état fiscal, et
            # c'est pourquoi le fragment de T4 n'était pas réutilisable ici.
            **document_exchange_panel(
                order.tenant, document_type=DOCUMENT_ORDER, document_id=order.id
            ),
            # Chatter (Sprint 3 / L2, cf.
            # docs/planning/2026-refonte-ux-sprints.md §5) : premiere
            # utilisation reelle du composant <c-chatter>, cf.
            # templates/cotton/chatter.html.
            # T8 (CON-1) — l'autre moitié de « toute pièce métier » : une
            # commande de vente part chez la boutique (T7), et son état
            # d'échange se lit ici plutôt que dans un journal séparé.
            **document_exchange_panel(
                order.tenant, document_type=DOCUMENT_ORDER, document_id=order.id
            ),
            "chatter_app_label": order._meta.app_label,
            "chatter_model": order._meta.model_name,
            "chatter_object_id": str(order.id),
        },
    )
