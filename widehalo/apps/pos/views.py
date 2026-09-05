"""Écrans HTMX du module `pos` (§13.5) : session-authentifié
(`@login_required`), appel direct aux `services/*` de `pos`, jamais
l'API JWT interne — même patron que `apps.stocks.views`/`apps.sales.views`.

**Deux gabarits seulement** (budget écrans, cf. `tests/architecture/
test_budget.py`) : `pos/index.html` (back-office — registres, moyens de
paiement, sessions, journal de synchronisation, chaque section pilotée
par `?tab=...`, même patron que `stocks/index.html`) et `pos/sale.html`
(écran de vente lui-même, seul écran du module — avec l'atelier de
simulation de la Phase 1 à venir — à embarquer de la logique locale
significative : cache du catalogue, panier, file de synchronisation hors
ligne, cf. cahier §11.1 "Deux exceptions assumées à la règle du rendu
serveur")."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounting.services.public import get_default_sale_tax
from apps.catalog.services.public import search_sellable_variants
from apps.core.views.tenant_web import resolve_tenant
from apps.partners.services.public import search_partners
from apps.pos.models import PosOrder, PosPaymentMethod, PosRegister, PosSession, PosSyncLog
from apps.pos.services.orders import mark_reprint, sync_order
from apps.pos.services.sessions import (
    add_cash_movement,
    close_session,
    compute_expected_cash,
    open_session,
)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _render(request: HttpRequest, active_tab: str, context: dict) -> HttpResponse:  # type: ignore[type-arg]
    context["active_tab"] = active_tab
    return render(request, "pos/index.html", context)


# ---------------------------------------------------------------------------
# Écran de vente
# ---------------------------------------------------------------------------


@login_required
def sale_screen(request: HttpRequest) -> HttpResponse:
    """Écran de caisse (POS-1) — rendu serveur classique, MAIS le panier et
    la soumission de vente sont pilotés par un composant Alpine.js (cf.
    cahier §11.1 : l'écran de caisse est l'une des deux exceptions
    assumées à la règle du rendu serveur, pour pouvoir fonctionner hors
    ligne). Catalogue, moyens de paiement et taux de TVA sont EMBARQUÉS
    dans la réponse initiale (`json_script`) — aucun appel réseau
    supplémentaire n'est nécessaire pour les charger, ce qui les rend
    disponibles même si le réseau tombe juste après le chargement de la
    page. La soumission elle-même passe par un `<form method="post">`
    ORDINAIRE (`pos:sale_submit`) : c'est ce qui permet au script
    générique `static/js/offline_queue.js` (déjà chargé par `base.html`,
    Sprint 10) de la mettre en file hors ligne SANS aucun code
    spécifique au POS — le `client_uuid` généré côté client est inclus
    dans le formulaire et rejoué tel quel à la reconnexion, garantissant
    l'idempotence (POS-3) au niveau de `services.orders.sync_order`."""
    if not request.user.has_perm("pos.add_posorder"):
        return HttpResponse(status=403)

    registers = PosRegister.objects.filter(is_active=True).order_by("code")
    my_open_session = (
        PosSession.objects.filter(cashier=request.user, state=PosSession.STATE_OPEN)
        .select_related("register")
        .first()
    )
    catalog = search_sellable_variants("", limit=500)
    payment_methods = list(
        PosPaymentMethod.objects.filter(is_active=True)
        .order_by("code")
        .values("id", "code", "name", "type", "requires_reference")
    )
    default_tax = get_default_sale_tax(resolve_tenant(request))
    tax_rate = default_tax["rate"] if default_tax else Decimal(0)
    last_order = None
    order_id = request.GET.get("order_id")
    if order_id:
        try:
            last_order = (
                PosOrder.objects.filter(id=uuid.UUID(order_id))
                .select_related("register")
                .prefetch_related("lines", "payments")
                .first()
            )
        except ValueError:
            last_order = None

    return render(
        request,
        "pos/sale.html",
        {
            "registers": registers,
            "my_open_session": my_open_session,
            "catalog": catalog,
            "payment_methods": [{**pm, "id": str(pm["id"])} for pm in payment_methods],
            "tax_rate": tax_rate,
            "last_order": last_order,
            "error": request.GET.get("error", ""),
        },
    )


@login_required
def sale_open_session(request: HttpRequest) -> HttpResponse:
    """Ouverture de session — action DISTINCTE de la vente elle-même,
    volontairement HORS du périmètre "hors ligne d'abord" : ouvrir sa
    caisse en début de journée suppose déjà un réseau disponible (cf.
    persona Caissier, cahier §3 — les coupures visées sont celles qui
    surviennent PENDANT le service, pas au tout premier geste)."""
    if request.method != "POST" or not request.user.has_perm("pos.add_possession"):
        return HttpResponse(status=403)
    register = get_object_or_404(PosRegister, id=request.POST.get("register_id"))
    try:
        amount = Decimal(request.POST.get("opening_cash_amount") or "0")
        open_session(
            resolve_tenant(request),
            register=register,
            cashier=request.user,
            opening_cash_amount=amount,
        )
    except (ValidationError, InvalidOperation) as exc:
        detail = _error_message(exc)
        return redirect(f"/pos/sale/?error={quote(detail)}")
    return redirect("pos:sale")


@login_required
def sale_submit(request: HttpRequest) -> HttpResponse:
    """Soumission d'une vente (ou d'un retour) construite côté client —
    voir `sale_screen` pour la raison d'être de ce `<form method="post">`
    ordinaire plutôt qu'un appel `fetch()` direct."""
    if request.method != "POST" or not request.user.has_perm("pos.add_posorder"):
        return HttpResponse(status=403)

    session = get_object_or_404(PosSession, id=request.POST.get("session_id"))
    try:
        # `parse_float=Decimal` : les montants (qty/unit_price/discount_pct/
        # amount) doivent arriver en `Decimal` pour les services `pos`
        # (jamais `float`, convention projet — cf. `apps.pos.schemas`, où
        # c'est pydantic qui fait cette coercion côté API ninja ; ici, un
        # `json.loads` brut, sans passage par un schema, doit le faire
        # explicitement).
        cart = json.loads(request.POST.get("cart_json") or "{}", parse_float=Decimal)
        order, _outcome = sync_order(
            resolve_tenant(request),
            session=session,
            client_uuid=uuid.UUID(cart["client_uuid"]),
            local_sequence=int(cart["local_sequence"]),
            order_type=cart.get("order_type", PosOrder.TYPE_SALE),
            document_type=cart.get("document_type", PosOrder.DOCUMENT_TICKET),
            partner_id=uuid.UUID(cart["partner_id"]) if cart.get("partner_id") else None,
            lines=cart.get("lines", []),
            payments=[
                {**payment, "method_id": uuid.UUID(payment["method_id"])}
                for payment in cart.get("payments", [])
            ],
            source=PosOrder.SOURCE_ONLINE,
            user=request.user,
        )
    except (ValidationError, KeyError, ValueError, TypeError) as exc:
        detail = _error_message(exc) if isinstance(exc, ValidationError) else str(exc)
        return redirect(f"/pos/sale/?error={quote(detail)}")
    return redirect(f"/pos/sale/?order_id={order.id}")


# Formats thermiques courants. 80 mm par defaut (le plus repandu), 58 mm
# pour les caisses mobiles/portables. Toute autre valeur est ignoree plutot
# que rendue : une largeur libre produirait un ticket illisible sur du
# materiel qui n'existe pas.
_TICKET_WIDTHS_MM = (80, 58)


def _resolve_ticket_width(raw: str | None) -> int:
    try:
        width = int(raw or "")
    except ValueError:
        return _TICKET_WIDTHS_MM[0]
    return width if width in _TICKET_WIDTHS_MM else _TICKET_WIDTHS_MM[0]


@login_required
def ticket_print(request: HttpRequest, order_id: str) -> HttpResponse:
    """POS-1 — impression du ticket de caisse.

    **L'ecran que `reprint_count` documentait sans qu'il existe.** Le
    compteur etait livre, incremente par `services.orders.mark_reprint`, et
    sa docstring annoncait « l'ecran d'impression affiche DUPLICATA des que
    reprint_count > 0 ». Cet ecran n'existait nulle part : le compteur
    tracait les reimpressions d'un document qu'aucun code ne produisait.

    LECTURE PURE — cette vue n'incremente rien. Recharger la page, revenir
    en arriere ou reimprimer depuis le navigateur ne doit jamais compter une
    reimpression, sans quoi la trace de duplicata ne voudrait plus rien
    dire. C'est `ticket_reprint` (POST) qui declare l'acte."""
    if not request.user.has_perm("pos.view_posorder"):
        return HttpResponse(status=403)

    order = get_object_or_404(
        PosOrder.objects.select_related("register").prefetch_related("lines", "payments__method"),
        id=order_id,
    )
    width = _resolve_ticket_width(request.GET.get("width"))
    return render(
        request,
        "pos/ticket.html",
        {
            "order": order,
            "tenant": resolve_tenant(request),
            "paper_width_mm": width,
            "other_width_mm": 58 if width == 80 else 80,
        },
    )


@login_required
def ticket_reprint(request: HttpRequest, order_id: str) -> HttpResponse:
    """Declare une reimpression (POST) puis renvoie sur le ticket.

    Separee de `ticket_print` parce qu'elle ECRIT : le cahier exige que la
    reimpression soit « autorisee mais tracee et marquee comme duplicata »,
    et une trace qu'un simple rechargement de page fait grimper ne trace
    rien."""
    if request.method != "POST" or not request.user.has_perm("pos.change_posorder"):
        return HttpResponse(status=403)

    order = get_object_or_404(PosOrder, id=order_id)
    mark_reprint(order)
    width = _resolve_ticket_width(request.POST.get("width"))
    return redirect(f"/pos/orders/{order.id}/ticket/?width={width}")


@login_required
def sale_partner_search(request: HttpRequest) -> JsonResponse:
    """Recherche client — convenience EN LIGNE uniquement (cf. docstring
    de `sale_screen` : un client ne peut pas être recherché hors ligne,
    le ticket reste anonyme dans ce cas, ce que le cahier autorise
    explicitement)."""
    if not request.user.has_perm("pos.view_posorder"):
        return JsonResponse({"detail": "forbidden"}, status=403)
    query = request.GET.get("q", "")
    results = search_partners(resolve_tenant(request), query, limit=10)
    return JsonResponse({"results": results})


# ---------------------------------------------------------------------------
# Back-office : registres
# ---------------------------------------------------------------------------


@login_required
def register_list(request: HttpRequest) -> HttpResponse:
    can_edit = request.user.has_perm("pos.add_posregister")
    if request.method == "POST":
        if not can_edit:
            return HttpResponse(status=403)
        code = request.POST.get("code", "").strip()
        name = request.POST.get("name", "").strip()
        warehouse_id = request.POST.get("warehouse_id") or None
        if code and name:
            PosRegister.objects.create(
                tenant=resolve_tenant(request),
                code=code,
                name=name,
                warehouse_id=warehouse_id,
                created_by=request.user,
            )
        return redirect("pos:index")

    registers = PosRegister.objects.order_by("code")
    return _render(request, "registers", {"registers": registers, "can_edit": can_edit})


# ---------------------------------------------------------------------------
# Back-office : moyens de paiement
# ---------------------------------------------------------------------------


@login_required
def payment_method_list(request: HttpRequest) -> HttpResponse:
    can_edit = request.user.has_perm("pos.add_pospaymentmethod")
    if request.method == "POST":
        if not can_edit:
            return HttpResponse(status=403)
        code = request.POST.get("code", "").strip()
        name = request.POST.get("name", "").strip()
        method_type = request.POST.get("type", PosPaymentMethod.TYPE_CASH)
        requires_reference = bool(request.POST.get("requires_reference"))
        if code and name:
            PosPaymentMethod.objects.create(
                tenant=resolve_tenant(request),
                code=code,
                name=name,
                type=method_type,
                requires_reference=requires_reference,
                created_by=request.user,
            )
        return redirect("pos:payment_methods")

    methods = PosPaymentMethod.objects.order_by("code")
    return _render(
        request,
        "payment_methods",
        {
            "methods": methods,
            "can_edit": can_edit,
            "type_choices": PosPaymentMethod.TYPE_CHOICES,
        },
    )


# ---------------------------------------------------------------------------
# Back-office : sessions de caisse
# ---------------------------------------------------------------------------


@login_required
def session_list(request: HttpRequest) -> HttpResponse:
    sessions = PosSession.objects.select_related("register", "cashier").order_by("-opened_at")[:100]
    return _render(request, "sessions", {"sessions": sessions})


@login_required
def session_detail(request: HttpRequest, session_id: str) -> HttpResponse:
    session = get_object_or_404(
        PosSession.objects.select_related("register", "cashier"), id=session_id
    )
    can_manage = (
        request.user.has_perm("pos.change_possession") or session.cashier_id == request.user.id
    )
    error = None

    if request.method == "POST":
        if not can_manage:
            return HttpResponse(status=403)
        action = request.POST.get("action")
        try:
            if action == "cash_movement":
                add_cash_movement(
                    session,
                    direction=request.POST.get("direction", ""),
                    amount=Decimal(request.POST.get("amount") or "0"),
                    reason=request.POST.get("reason", ""),
                    user=request.user,
                )
            elif action == "close":
                close_session(
                    session,
                    counted_cash=Decimal(request.POST.get("counted_cash") or "0"),
                    variance_reason=request.POST.get("variance_reason", ""),
                    user=request.user,
                )
        except (ValidationError, InvalidOperation) as exc:
            error = _error_message(exc)
        else:
            return redirect("pos:session_detail", session_id=session.id)

    expected_cash = (
        compute_expected_cash(session) if session.state == PosSession.STATE_OPEN else None
    )
    return _render(
        request,
        "sessions",
        {
            "sessions": PosSession.objects.select_related("register", "cashier").order_by(
                "-opened_at"
            )[:100],
            "selected_session": session,
            "expected_cash": expected_cash,
            "can_manage": can_manage,
            "error": error,
            "cash_movements": session.cash_movements.order_by("-created_at"),
        },
    )


# ---------------------------------------------------------------------------
# Back-office : journal de synchronisation
# ---------------------------------------------------------------------------


@login_required
def sync_log_view(request: HttpRequest) -> HttpResponse:
    logs = PosSyncLog.objects.select_related("register", "session").order_by("-synced_at")[:200]
    return _render(request, "sync_log", {"logs": logs})
