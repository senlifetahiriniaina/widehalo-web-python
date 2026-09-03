"""Commandes de caisse — création, lignes, règlements, validation,
retours/avoirs, synchronisation hors ligne idempotente (POS-1 à POS-5,
POS-8, cahier §13.5)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.services.public import get_default_sale_tax
from apps.catalog.services.public import get_variant_price, is_variant_sellable
from apps.core.services.sequences import next_reference
from apps.pos.models import (
    PosOrder,
    PosOrderLine,
    PosPayment,
    PosPaymentMethod,
    PosSession,
    PosSyncLog,
)
from apps.pos.services.scoping import assert_can_manage_session
from apps.stocks.services.public import receive_pos_return, sell_from_stock

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

_AMOUNT_QUANT = Decimal("0.0001")


def _ensure_session_open(session: PosSession) -> None:
    # POS-2/POS-9 : aucune vente hors session ouverte, jamais de mutation
    # sur une session déjà clôturée — vérifié à CHAQUE étape de
    # construction d'une commande (creation, ligne, règlement,
    # validation), pas seulement à la création.
    if session.state != PosSession.STATE_OPEN:
        raise ValidationError(_("Impossible d'opérer sur une session de caisse clôturée."))


def create_draft_order(
    tenant: Tenant,
    *,
    session: PosSession,
    client_uuid: UUID,
    local_sequence: int,
    order_type: str = PosOrder.TYPE_SALE,
    document_type: str = PosOrder.DOCUMENT_TICKET,
    partner_id: Any = None,
    origin_order: PosOrder | None = None,
    source: str = PosOrder.SOURCE_ONLINE,
    user: User | None = None,
) -> PosOrder:
    _ensure_session_open(session)
    if user is not None:
        assert_can_manage_session(session, user)
    if document_type == PosOrder.DOCUMENT_INVOICE and partner_id is None:
        raise ValidationError(_("Une facture nominative exige un client identifié."))
    return PosOrder.objects.create(
        tenant=tenant,
        session=session,
        register=session.register,
        client_uuid=client_uuid,
        local_sequence=local_sequence,
        order_type=order_type,
        document_type=document_type,
        partner_id=partner_id,
        origin_order=origin_order,
        source=source,
        created_by=user,
    )


def _recompute_order_totals(order: PosOrder) -> None:
    agg = order.lines.aggregate(
        untaxed=Sum("subtotal"), tax=Sum("tax_amount"), total=Sum("total")
    )
    order.amount_untaxed = agg["untaxed"] or Decimal(0)
    order.amount_tax = agg["tax"] or Decimal(0)
    order.amount_total = agg["total"] or Decimal(0)
    order.save(update_fields=["amount_untaxed", "amount_tax", "amount_total"])


def add_line(
    order: PosOrder,
    *,
    line_type: str = PosOrderLine.TYPE_PRODUCT,
    variant_id: Any = None,
    description: str = "",
    qty: Decimal = Decimal(1),
    uom: str = "",
    unit_price: Decimal | None = None,
    discount_pct: Decimal = Decimal(0),
    service_basis: str = "",
    is_deposit: bool = False,
) -> PosOrderLine:
    """POS-1/POS-8 : `line_type=SERVICE` ne référence JAMAIS de
    `variant_id` et ne génère JAMAIS de mouvement de stock (revalidé à la
    validation, `validate_order`) — le prix d'une ligne produit est
    revalidé côté serveur via `catalog.services.public.
    is_variant_sellable`/`get_variant_price`, jamais fait confiance à un
    prix fourni par le client sans un `unit_price` explicite (permis pour
    une ligne de service, dont le tarif n'a pas de source catalogue)."""
    _ensure_session_open(order.session)
    if order.state != PosOrder.STATE_DRAFT:
        raise ValidationError(_("Impossible de modifier une commande déjà validée ou annulée."))
    if qty <= 0:
        raise ValidationError(_("La quantité d'une ligne doit être positive."))

    if line_type == PosOrderLine.TYPE_PRODUCT:
        if variant_id is None:
            raise ValidationError(
                _("Une ligne de produit doit référencer un article du catalogue.")
            )
        if not is_variant_sellable(variant_id):
            raise ValidationError(_("Cet article n'est pas vendable."))
        if unit_price is None:
            unit_price = get_variant_price(variant_id, partner_id=order.partner_id)
    else:
        variant_id = None
        if unit_price is None:
            unit_price = Decimal(0)

    tax = get_default_sale_tax(order.tenant)
    tax_id = tax["id"] if tax else None
    tax_rate = tax["rate"] if tax else Decimal(0)

    gross = qty * unit_price
    discount_amount = gross * discount_pct / Decimal(100)
    subtotal = (gross - discount_amount).quantize(_AMOUNT_QUANT)
    tax_amount = (subtotal * tax_rate / Decimal(100)).quantize(_AMOUNT_QUANT)
    total = subtotal + tax_amount

    line = PosOrderLine.objects.create(
        tenant=order.tenant,
        order=order,
        sequence=order.lines.count(),
        line_type=line_type,
        variant_id=variant_id,
        description=description,
        qty=qty,
        uom=uom,
        unit_price=unit_price,
        discount_pct=discount_pct,
        tax_id=tax_id,
        tax_rate=tax_rate,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        service_basis=service_basis,
        is_deposit=is_deposit,
    )
    _recompute_order_totals(order)
    return line


def add_return_line(order: PosOrder, *, origin_line: PosOrderLine, qty: Decimal) -> PosOrderLine:
    """Ligne de retour/avoir — reprend TOUJOURS le prix/la remise/le taux
    de TVA de la ligne d'ORIGINE (jamais le prix catalogue courant, qui a
    pu changer depuis la vente) au prorata de `qty` retournée vs la
    quantité initialement vendue (cahier : "Retour partiel ou total
    rattaché au ticket d'origine")."""
    _ensure_session_open(order.session)
    if order.order_type != PosOrder.TYPE_RETURN:
        raise ValidationError(_("Seule une commande de type retour peut recevoir une ligne de retour."))
    if order.state != PosOrder.STATE_DRAFT:
        raise ValidationError(_("Impossible de modifier une commande déjà validée ou annulée."))
    if qty <= 0 or qty > origin_line.qty:
        raise ValidationError(_("Quantité de retour invalide."))

    ratio = qty / origin_line.qty
    subtotal = (origin_line.subtotal * ratio).quantize(_AMOUNT_QUANT)
    tax_amount = (origin_line.tax_amount * ratio).quantize(_AMOUNT_QUANT)
    total = subtotal + tax_amount

    line = PosOrderLine.objects.create(
        tenant=order.tenant,
        order=order,
        sequence=order.lines.count(),
        line_type=origin_line.line_type,
        variant_id=origin_line.variant_id,
        description=origin_line.description,
        qty=qty,
        uom=origin_line.uom,
        unit_price=origin_line.unit_price,
        discount_pct=origin_line.discount_pct,
        tax_id=origin_line.tax_id,
        tax_rate=origin_line.tax_rate,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        service_basis=origin_line.service_basis,
    )
    _recompute_order_totals(order)
    return line


def add_payment(
    order: PosOrder,
    *,
    method: PosPaymentMethod,
    amount: Decimal,
    reference: str = "",
    received_at: dt.datetime | None = None,
    user: User | None = None,
) -> PosPayment:
    """POS-5 : `reference` obligatoire pour tout moyen marqué
    `requires_reference` (mobile money — "la référence de transaction du
    mobile money est obligatoire et conservée avec la vente")."""
    _ensure_session_open(order.session)
    if order.state != PosOrder.STATE_DRAFT:
        raise ValidationError(
            _("Impossible d'ajouter un règlement à une commande déjà validée ou annulée.")
        )
    if amount <= 0:
        raise ValidationError(_("Le montant d'un règlement doit être positif."))
    if method.requires_reference and not reference.strip():
        raise ValidationError(
            _("Une référence de transaction est obligatoire pour ce moyen de paiement.")
        )
    return PosPayment.objects.create(
        tenant=order.tenant,
        order=order,
        method=method,
        amount=amount,
        reference=reference,
        received_at=received_at or timezone.now(),
        created_by=user,
    )


@transaction.atomic
def validate_order(order: PosOrder, *, user: User | None = None, date: dt.date | None = None) -> PosOrder:
    """POS-1/POS-4/POS-7/POS-8 : fige la commande — assigne le numéro
    définitif réconcilié serveur (`apps.core.services.sequences.
    next_reference`, préfixe = `register.code`), sort/reçoit le stock des
    lignes produit (`stocks.services.public.sell_from_stock`/
    `receive_pos_return` — JAMAIS pour une ligne de service, POS-8),
    exige un règlement intégral avant validation."""
    _ensure_session_open(order.session)
    if order.state != PosOrder.STATE_DRAFT:
        raise ValidationError(_("Cette commande est déjà validée ou annulée."))
    if not order.lines.exists():
        raise ValidationError(_("Une commande sans ligne ne peut pas être validée."))
    if order.document_type == PosOrder.DOCUMENT_INVOICE and order.partner_id is None:
        raise ValidationError(_("Une facture nominative exige un client identifié."))

    paid_total = order.payments.aggregate(total=Sum("amount"))["total"] or Decimal(0)
    if paid_total != order.amount_total:
        raise ValidationError(
            _("Le total des règlements ne correspond pas au total de la commande.")
        )

    validate_date = date or timezone.now().date()
    register = order.register

    for line in order.lines.filter(line_type=PosOrderLine.TYPE_PRODUCT):
        if register.warehouse_id is None or line.variant_id is None:
            continue
        if order.order_type == PosOrder.TYPE_SALE:
            picking_id = sell_from_stock(
                order.tenant,
                variant_id=line.variant_id,
                qty=line.qty,
                warehouse_id=register.warehouse_id,
                date=validate_date,
                source_document=order.number or str(order.client_uuid),
                operator=user,
            )
        else:
            picking_id = receive_pos_return(
                order.tenant,
                variant_id=line.variant_id,
                qty=line.qty,
                warehouse_id=register.warehouse_id,
                date=validate_date,
                source_document=order.number or str(order.client_uuid),
                operator=user,
            )
        if picking_id is not None:
            line.stock_move_id = picking_id
            line.save(update_fields=["stock_move_id"])

    order.number = next_reference(order.tenant, order.register.code, validate_date.year)
    order.state = PosOrder.STATE_VALIDATED
    order.updated_by = user
    order.save(update_fields=["number", "state", "updated_by"])
    return order


def cancel_order(order: PosOrder, *, user: User | None = None) -> PosOrder:
    """Seule une commande en BROUILLON peut être annulée — une commande
    validée est immuable (POS-9) ; l'annuler reviendrait à une suppression
    déguisée. Une vente validée ne se corrige que par un retour/avoir
    (`create_return_order`)."""
    if order.state != PosOrder.STATE_DRAFT:
        raise ValidationError(_("Seule une commande en brouillon peut être annulée."))
    order.state = PosOrder.STATE_CANCELLED
    order.updated_by = user
    order.save(update_fields=["state", "updated_by"])
    return order


def mark_reprint(order: PosOrder) -> PosOrder:
    """Réimpression AUTORISÉE mais TRACÉE (cahier, écran "Ticket et
    facture" : "réimpression autorisée mais tracée et marquée comme
    duplicata") — le compteur seul suffit à la traçabilité, l'écran
    d'impression affiche "DUPLICATA" dès que `reprint_count > 0`."""
    order.reprint_count += 1
    order.save(update_fields=["reprint_count"])
    return order


@transaction.atomic
def create_return_order(
    tenant: Tenant,
    *,
    origin_order: PosOrder,
    session: PosSession,
    client_uuid: UUID,
    local_sequence: int,
    return_lines: list[dict[str, Any]],
    refund_method: PosPaymentMethod,
    refund_reference: str = "",
    user: User | None = None,
    date: dt.date | None = None,
) -> PosOrder:
    """Retour/avoir complet en une transaction : crée la commande de type
    RETURN rattachée au ticket d'origine, ajoute les lignes retournées
    (`return_lines` : `[{"origin_line_id": UUID, "qty": Decimal}, ...]`),
    règle intégralement l'avoir sur `refund_method`, puis valide."""
    if origin_order.order_type != PosOrder.TYPE_SALE or origin_order.state != PosOrder.STATE_VALIDATED:
        raise ValidationError(_("Seule une vente validée peut faire l'objet d'un retour."))

    order = create_draft_order(
        tenant,
        session=session,
        client_uuid=client_uuid,
        local_sequence=local_sequence,
        order_type=PosOrder.TYPE_RETURN,
        document_type=origin_order.document_type,
        partner_id=origin_order.partner_id,
        origin_order=origin_order,
        source=PosOrder.SOURCE_ONLINE,
        user=user,
    )
    origin_lines = {line.id: line for line in origin_order.lines.all()}
    for spec in return_lines:
        origin_line = origin_lines.get(spec["origin_line_id"])
        if origin_line is None:
            raise ValidationError(_("Ligne d'origine introuvable sur le ticket retourné."))
        add_return_line(order, origin_line=origin_line, qty=spec["qty"])

    order.refresh_from_db()
    add_payment(
        order,
        method=refund_method,
        amount=order.amount_total,
        reference=refund_reference,
        user=user,
    )
    validate_order(order, user=user, date=date)
    return order


def sync_order(
    tenant: Tenant,
    *,
    session: PosSession,
    client_uuid: UUID,
    local_sequence: int,
    order_type: str,
    document_type: str,
    partner_id: Any,
    lines: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    source: str,
    user: User | None = None,
    date: dt.date | None = None,
) -> tuple[PosOrder, str]:
    """Point d'entrée UNIQUE et idempotent de création d'une commande —
    utilisé pour la vente en ligne (`source=ONLINE`, un appel = une vente
    immédiate) comme pour le rejeu d'une file hors ligne (`source=OFFLINE`,
    POS-3 : potentiellement rejoué plusieurs fois pour le MÊME
    `client_uuid` après une coupure réseau).

    `client_uuid` déjà connu (`PosOrder` existant) => AUCUNE nouvelle
    commande, aucune double comptabilisation : la commande existante est
    retournée telle quelle, un `PosSyncLog` "duplicate" est journalisé
    (POS-3/POS-4 : "ni trou, ni doublon"). Toute autre erreur de
    validation (session close, stock insuffisant...) est journalisée en
    "rejected" AVANT d'être relevée telle quelle à l'appelant (jamais
    avalée — l'appelant/l'écran de caisse doit savoir qu'une vente en
    attente a été refusée pour pouvoir la présenter au caissier).

    **Volontairement PAS `@transaction.atomic` sur cette fonction
    elle-même** (contrairement à `create_return_order` ci-dessus) : seule
    la construction de la commande (`with transaction.atomic():`
    ci-dessous) doit être annulée en cas d'échec, JAMAIS le
    `PosSyncLog.objects.create()` de la branche `except`, qui doit
    survivre au `raise` final — un décorateur englobant aurait annulé ce
    dernier avec le reste dès que l'exception se propage hors de la
    fonction (le rollback d'un bloc atomique s'applique à TOUT ce bloc,
    y compris une écriture faite APRÈS la récupération d'un rollback
    imbriqué, si ce bloc englobant échoue lui-même ensuite — constaté
    empiriquement en écrivant ce module : le premier jet, décoré
    `@transaction.atomic`, perdait silencieusement le `PosSyncLog`
    "rejected" à chaque échec)."""
    existing = PosOrder.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
    if existing is not None:
        PosSyncLog.objects.create(
            tenant=tenant,
            register=existing.register,
            session=existing.session,
            order=existing,
            client_uuid=client_uuid,
            local_sequence=existing.local_sequence,
            outcome=PosSyncLog.OUTCOME_DUPLICATE,
            detail=_("Commande déjà synchronisée, rejeu ignoré."),
            synced_at=timezone.now(),
        )
        return existing, PosSyncLog.OUTCOME_DUPLICATE

    try:
        with transaction.atomic():
            order = create_draft_order(
                tenant,
                session=session,
                client_uuid=client_uuid,
                local_sequence=local_sequence,
                order_type=order_type,
                document_type=document_type,
                partner_id=partner_id,
                source=source,
                user=user,
            )
            for spec in lines:
                add_line(order, **spec)
            for spec in payments:
                method = PosPaymentMethod.objects.get(tenant=tenant, id=spec["method_id"])
                add_payment(
                    order,
                    method=method,
                    amount=spec["amount"],
                    reference=spec.get("reference", ""),
                    received_at=spec.get("received_at"),
                    user=user,
                )
            validate_order(order, user=user, date=date)
    except ValidationError as exc:
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        PosSyncLog.objects.create(
            tenant=tenant,
            register=session.register,
            session=session,
            order=None,
            client_uuid=client_uuid,
            local_sequence=local_sequence,
            outcome=PosSyncLog.OUTCOME_REJECTED,
            detail=detail,
            synced_at=timezone.now(),
        )
        raise

    PosSyncLog.objects.create(
        tenant=tenant,
        register=order.register,
        session=session,
        order=order,
        client_uuid=client_uuid,
        local_sequence=local_sequence,
        outcome=PosSyncLog.OUTCOME_ACCEPTED,
        detail="",
        synced_at=timezone.now(),
    )
    return order, PosSyncLog.OUTCOME_ACCEPTED
