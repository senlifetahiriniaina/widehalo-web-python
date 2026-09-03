"""API django-ninja du module `pos` (§13.5) — authentifiée par jeton JWT
(`config.api.api`, cf. sa docstring de tete : "API interne... liste
blanche" et "API externe... authentifiee par jeton par tenant"). Surface
programmatique complete (back-office + cycle de vente + synchronisation
hors ligne + retours), exposee pour un futur client natif/mobile ou une
integration tierce — PAS la surface reellement consommee par l'ecran de
caisse web actuel.

**L'écran de caisse web (`templates/pos/sale.html`) N'APPELLE JAMAIS ces
endpoints** : une page HTML authentifiée par SESSION (cookie Django) n'a
pas de jeton JWT à présenter à `JWTAuth` sans mécanisme de pont
supplémentaire, qu'aucun autre écran de ce dépôt ne construit (vérifié :
aucun fichier de `static/js/` n'appelle `/api/v1/...`, cf. `apps.pos.
views`, tous les écrans HTMX du dépôt passent exclusivement par des vues
Django classiques). L'écran de caisse utilise donc ses propres vues
session-authentifiées dédiées (`apps.pos.views.sale_submit`/
`sale_partner_search`, un `<form method="post">` ordinaire intercepté par
`static/js/offline_queue.js` pour le hors ligne, cf. leurs docstrings) —
qui appellent les MÊMES fonctions de `apps.pos.services.*` que ce
routeur, jamais une logique dupliquée."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.accounting.services.public import get_default_sale_tax
from apps.catalog.services.public import search_sellable_variants
from apps.core.services.permissions import require_permission
from apps.partners.services.public import get_partner_display_name, search_partners
from apps.pos.models import (
    PosCashMovement,
    PosOrder,
    PosPaymentMethod,
    PosRegister,
    PosSession,
    PosSyncLog,
)
from apps.pos.schemas import (
    CashMovementIn,
    CatalogSearchOut,
    OrderOut,
    OrderSyncBatchIn,
    OrderSyncResultOut,
    PartnerSearchOut,
    PaymentMethodIn,
    PaymentMethodOut,
    RegisterIn,
    RegisterOut,
    ReturnOrderIn,
    SessionCloseIn,
    SessionClosingPreviewOut,
    SessionOpenIn,
    SessionOut,
    SyncLogOut,
)
from apps.pos.services.orders import cancel_order, create_return_order, mark_reprint, sync_order
from apps.pos.services.sessions import add_cash_movement, close_session, compute_expected_cash, open_session

router = Router(tags=["pos"])


def _tenant(request):  # type: ignore[no-untyped-def]
    from apps.core.models.tenant import Tenant

    return Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))


def _serialize_register(register: PosRegister) -> RegisterOut:
    return RegisterOut(
        id=str(register.id),
        code=register.code,
        name=register.name,
        warehouse_id=str(register.warehouse_id) if register.warehouse_id else None,
        is_active=register.is_active,
    )


def _serialize_payment_method(method: PosPaymentMethod) -> PaymentMethodOut:
    return PaymentMethodOut(
        id=str(method.id),
        code=method.code,
        name=method.name,
        type=method.type,
        requires_reference=method.requires_reference,
        default_account_type=method.default_account_type,
        account_id=str(method.account_id) if method.account_id else None,
        is_active=method.is_active,
    )


def _serialize_session(session: PosSession) -> SessionOut:
    return SessionOut(
        id=str(session.id),
        register_id=str(session.register_id),
        register_code=session.register.code,
        cashier_id=str(session.cashier_id),
        state=session.state,
        opened_at=session.opened_at,
        closed_at=session.closed_at,
        opening_cash_amount=session.opening_cash_amount,
        closing_cash_counted=session.closing_cash_counted,
        closing_cash_expected=session.closing_cash_expected,
        cash_variance=session.cash_variance,
        cash_variance_reason=session.cash_variance_reason,
        closing_move_id=str(session.closing_move_id) if session.closing_move_id else None,
        local_sequence_last=session.local_sequence_last,
    )


def _serialize_order(order: PosOrder) -> OrderOut:
    return OrderOut(
        id=str(order.id),
        session_id=str(order.session_id),
        register_code=order.register.code,
        client_uuid=str(order.client_uuid),
        number=order.number,
        local_sequence=order.local_sequence,
        order_type=order.order_type,
        origin_order_id=str(order.origin_order_id) if order.origin_order_id else None,
        document_type=order.document_type,
        partner_id=str(order.partner_id) if order.partner_id else None,
        partner_name=get_partner_display_name(order.partner_id) if order.partner_id else "",
        state=order.state,
        source=order.source,
        amount_untaxed=order.amount_untaxed,
        amount_tax=order.amount_tax,
        amount_total=order.amount_total,
        reprint_count=order.reprint_count,
        created_at=order.created_at,
        lines=[
            {
                "id": str(line.id),
                "sequence": line.sequence,
                "line_type": line.line_type,
                "variant_id": str(line.variant_id) if line.variant_id else None,
                "description": line.description,
                "qty": line.qty,
                "uom": line.uom,
                "unit_price": line.unit_price,
                "discount_pct": line.discount_pct,
                "tax_rate": line.tax_rate,
                "subtotal": line.subtotal,
                "tax_amount": line.tax_amount,
                "total": line.total,
                "service_basis": line.service_basis,
                "is_deposit": line.is_deposit,
                "stock_move_id": str(line.stock_move_id) if line.stock_move_id else None,
            }
            for line in order.lines.all()
        ],
        payments=[
            {
                "id": str(payment.id),
                "method_id": str(payment.method_id),
                "method_name": payment.method.name,
                "amount": payment.amount,
                "reference": payment.reference,
                "received_at": payment.received_at,
            }
            for payment in order.payments.select_related("method").all()
        ],
    )


# ---------------------------------------------------------------------------
# Back-office : registres, moyens de paiement
# ---------------------------------------------------------------------------


@router.get("/pos/registers")
@require_permission("pos.view_posregister")
def list_registers(request):  # type: ignore[no-untyped-def]
    registers = PosRegister.objects.filter(is_active=True).order_by("code")
    return {"results": [_serialize_register(r) for r in registers]}


@router.post("/pos/registers")
@require_permission("pos.add_posregister")
def create_register(request, payload: RegisterIn):  # type: ignore[no-untyped-def]
    register = PosRegister.objects.create(
        tenant=_tenant(request),
        code=payload.code,
        name=payload.name,
        warehouse_id=uuid.UUID(payload.warehouse_id) if payload.warehouse_id else None,
        created_by=request.auth,
    )
    return _serialize_register(register)


@router.get("/pos/payment-methods")
@require_permission("pos.view_pospaymentmethod")
def list_payment_methods(request):  # type: ignore[no-untyped-def]
    methods = PosPaymentMethod.objects.filter(is_active=True).order_by("code")
    return {"results": [_serialize_payment_method(m) for m in methods]}


@router.post("/pos/payment-methods")
@require_permission("pos.add_pospaymentmethod")
def create_payment_method(request, payload: PaymentMethodIn):  # type: ignore[no-untyped-def]
    method = PosPaymentMethod.objects.create(
        tenant=_tenant(request),
        code=payload.code,
        name=payload.name,
        type=payload.type,
        requires_reference=payload.requires_reference,
        default_account_type=payload.default_account_type,
        account_id=uuid.UUID(payload.account_id) if payload.account_id else None,
        created_by=request.auth,
    )
    return _serialize_payment_method(method)


# ---------------------------------------------------------------------------
# Sessions de caisse (POS-2, POS-6, POS-9)
# ---------------------------------------------------------------------------


@router.get("/pos/sessions")
@require_permission("pos.view_possession")
def list_sessions(request, mine: bool = False, state: str = ""):  # type: ignore[no-untyped-def]
    sessions = PosSession.objects.select_related("register").order_by("-opened_at")
    if mine:
        sessions = sessions.filter(cashier=request.auth)
    if state:
        sessions = sessions.filter(state=state)
    return {"results": [_serialize_session(s) for s in sessions[:100]]}


@router.post("/pos/sessions")
@require_permission("pos.add_possession")
def open_session_endpoint(request, payload: SessionOpenIn):  # type: ignore[no-untyped-def]
    register = get_object_or_404(PosRegister, id=payload.register_id)
    try:
        session = open_session(
            _tenant(request),
            register=register,
            cashier=request.auth,
            opening_cash_amount=payload.opening_cash_amount,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_session(session)


@router.get("/pos/sessions/{session_id}")
@require_permission("pos.view_possession")
def get_session_endpoint(request, session_id: str):  # type: ignore[no-untyped-def]
    session = get_object_or_404(PosSession.objects.select_related("register"), id=session_id)
    return _serialize_session(session)


@router.post("/pos/sessions/{session_id}/cash-movements")
@require_permission("pos.change_possession")
def add_cash_movement_endpoint(request, session_id: str, payload: CashMovementIn):  # type: ignore[no-untyped-def]
    session = get_object_or_404(PosSession, id=session_id)
    try:
        add_cash_movement(
            session,
            direction=payload.direction,
            amount=payload.amount,
            reason=payload.reason,
            user=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_session(session)


@router.get("/pos/sessions/{session_id}/closing-preview", response=SessionClosingPreviewOut)
@require_permission("pos.view_possession")
def closing_preview_endpoint(request, session_id: str):  # type: ignore[no-untyped-def]
    session = get_object_or_404(PosSession, id=session_id)
    return SessionClosingPreviewOut(
        expected_cash=compute_expected_cash(session),
        opening_cash_amount=session.opening_cash_amount,
    )


@router.post("/pos/sessions/{session_id}/close")
@require_permission("pos.change_possession")
def close_session_endpoint(request, session_id: str, payload: SessionCloseIn):  # type: ignore[no-untyped-def]
    session = get_object_or_404(PosSession, id=session_id)
    try:
        close_session(
            session,
            counted_cash=payload.counted_cash,
            variance_reason=payload.variance_reason,
            user=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_session(session)


# ---------------------------------------------------------------------------
# Écran de vente : recherche catalogue/client, synchronisation, retours
# ---------------------------------------------------------------------------


@router.get("/pos/catalog/search", response=list[CatalogSearchOut])
@require_permission("pos.view_posorder")
def catalog_search_endpoint(request, q: str = "", limit: int = 20):  # type: ignore[no-untyped-def]
    return [CatalogSearchOut(**row) for row in search_sellable_variants(q, limit=limit)]


@router.get("/pos/partners/search", response=list[PartnerSearchOut])
@require_permission("pos.view_posorder")
def partner_search_endpoint(request, q: str = "", limit: int = 20):  # type: ignore[no-untyped-def]
    return [
        PartnerSearchOut(**row) for row in search_partners(_tenant(request), q, limit=limit)
    ]


@router.get("/pos/sale-tax")
@require_permission("pos.view_posorder")
def sale_tax_endpoint(request):  # type: ignore[no-untyped-def]
    tax = get_default_sale_tax(_tenant(request))
    if tax is None:
        return {"rate": Decimal(0)}
    return {"rate": tax["rate"]}


@router.get("/pos/orders")
@require_permission("pos.view_posorder")
def list_orders_endpoint(request, session_id: str):  # type: ignore[no-untyped-def]
    orders = (
        PosOrder.objects.filter(session_id=session_id)
        .select_related("register")
        .prefetch_related("lines", "payments", "payments__method")
        .order_by("-created_at")
    )
    return {"results": [_serialize_order(o) for o in orders]}


@router.post("/pos/orders/sync", response=list[OrderSyncResultOut])
@require_permission("pos.add_posorder")
def sync_orders_endpoint(request, payload: OrderSyncBatchIn):  # type: ignore[no-untyped-def]
    """POS-3 : synchronisation par LOT — un client programmatique (cf.
    docstring de tête de ce module) rejoue ici sa file locale (une ou
    plusieurs ventes en attente) à la reconnexion. Une commande rejetée
    (session close, stock insuffisant, règlement incomplet...)
    N'INTERROMPT PAS le traitement des suivantes du même lot — chaque
    commande est indépendante (`services.orders.sync_order` est déjà
    atomique par commande), l'erreur est renvoyée inline pour CETTE
    commande plutôt que de faire échouer tout le lot.

    **Déclarée AVANT `/pos/orders/{order_id}` ci-dessous, volontairement**
    : même bug de routage que celui documenté sur `POST /partners/merge`
    dans `apps.core.tests.test_rbac_matrix` (`KNOWN_ROUTING_SHADOWED`) —
    le convertisseur `str` de `{order_id}` matche aussi le segment
    littéral "sync" ; ninja/Django résolvent les URLs dans l'ordre de
    déclaration, donc une déclaration inversée aurait rendu cet endpoint
    inatteignable via HTTP (capturé en amont par le PathView de
    `{order_id}`, qui ne connaît que GET -> 405 avant même l'évaluation
    de l'authentification). Constaté empiriquement en écrivant ce module
    (échec de `test_anonymous_is_denied_on_every_protected_operation`),
    corrigé ici plutôt que documenté comme un nouvel écart connu."""
    session = get_object_or_404(PosSession, id=payload.session_id)
    tenant = _tenant(request)
    results = []
    for spec in payload.orders:
        try:
            order, outcome = sync_order(
                tenant,
                session=session,
                client_uuid=uuid.UUID(spec.client_uuid),
                local_sequence=spec.local_sequence,
                order_type=spec.order_type,
                document_type=spec.document_type,
                partner_id=uuid.UUID(spec.partner_id) if spec.partner_id else None,
                lines=[line.dict() for line in spec.lines],
                payments=[
                    {**payment.dict(), "method_id": uuid.UUID(payment.dict()["method_id"])}
                    for payment in spec.payments
                ],
                source=spec.source,
                user=request.auth,
            )
        except ValidationError as exc:
            results.append(
                {
                    "outcome": "rejected",
                    "detail": "; ".join(exc.messages),
                    "client_uuid": spec.client_uuid,
                }
            )
            continue
        results.append(
            {"order": _serialize_order(order), "outcome": outcome, "client_uuid": spec.client_uuid}
        )
    return results


@router.get("/pos/orders/{order_id}")
@require_permission("pos.view_posorder")
def get_order_endpoint(request, order_id: str):  # type: ignore[no-untyped-def]
    order = get_object_or_404(
        PosOrder.objects.select_related("register").prefetch_related(
            "lines", "payments", "payments__method"
        ),
        id=order_id,
    )
    return _serialize_order(order)


@router.post("/pos/orders/{order_id}/reprint")
@require_permission("pos.change_posorder")
def reprint_order_endpoint(request, order_id: str):  # type: ignore[no-untyped-def]
    order = get_object_or_404(PosOrder, id=order_id)
    mark_reprint(order)
    return _serialize_order(order)


@router.post("/pos/orders/{order_id}/cancel")
@require_permission("pos.change_posorder")
def cancel_order_endpoint(request, order_id: str):  # type: ignore[no-untyped-def]
    order = get_object_or_404(PosOrder, id=order_id)
    try:
        cancel_order(order, user=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.post("/pos/returns")
@require_permission("pos.add_posorder")
def create_return_endpoint(request, payload: ReturnOrderIn):  # type: ignore[no-untyped-def]
    origin_order = get_object_or_404(PosOrder, id=payload.origin_order_id)
    session = get_object_or_404(PosSession, id=payload.session_id)
    refund_method = get_object_or_404(PosPaymentMethod, id=payload.refund_method_id)
    try:
        order = create_return_order(
            _tenant(request),
            origin_order=origin_order,
            session=session,
            client_uuid=uuid.UUID(payload.client_uuid),
            local_sequence=payload.local_sequence,
            return_lines=[
                {"origin_line_id": uuid.UUID(line.origin_line_id), "qty": line.qty}
                for line in payload.return_lines
            ],
            refund_method=refund_method,
            refund_reference=payload.refund_reference,
            user=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return _serialize_order(order)


@router.get("/pos/sync-log")
@require_permission("pos.view_possynclog")
def sync_log_endpoint(request, session_id: str = ""):  # type: ignore[no-untyped-def]
    logs = PosSyncLog.objects.select_related("register").order_by("-synced_at")
    if session_id:
        logs = logs.filter(session_id=session_id)
    return {
        "results": [
            SyncLogOut(
                id=str(log.id),
                register_code=log.register.code,
                client_uuid=str(log.client_uuid),
                local_sequence=log.local_sequence,
                outcome=log.outcome,
                detail=log.detail,
                synced_at=log.synced_at,
            )
            for log in logs[:200]
        ]
    }
