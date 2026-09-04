"""RG-PUR-5 (§5.6.5, PU5 du sous-sequencement `purchase` — cf. plan) :
reception partielle tracee, controle qualite, recalcul automatique de
l'etat FSM de `PurOrder`, et ecart reception vs commande
(`order_reception_variance`).

Cahier des charges Phase 3 (§12.1, decision P2) : `receiving_setup`/
`_order_in_transit` configurent desormais toujours un entrepot + un
emplacement interne valides (`StkWarehouse`/`StkLocation`), devenus une
precondition reelle de la reception (`receive_order_line` refuse sinon,
cf. `test_receive_order_line_refuses_without_a_configured_warehouse`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductTemplate, ProductVariant, UnitConversion, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurOrder, PurReceiptLine
from apps.purchase.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    mark_order_in_transit,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.receiving import order_reception_variance, receive_order_line
from apps.stocks.models import StkLocation, StkQuant, StkWarehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def receiving_setup():
    tenant = Tenant.objects.create(code="PUR-REC", name="Purchase Receiving Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="pur-rec@example.com", password="Str0ngPassw0rd!23")
        warehouse = StkWarehouse.objects.create(tenant=tenant, code="WH-PUR-REC", name="Entrepôt")
        internal_location = StkLocation.objects.create(
            tenant=tenant,
            warehouse=warehouse,
            code="WH-PUR-REC-A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        return tenant, user, warehouse, internal_location


def _order_in_transit(tenant, user, *, lines=1, warehouse_id=None):
    order = create_order(
        tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today(), warehouse_id=warehouse_id
    )
    created_lines = []
    for i in range(lines):
        created_lines.append(
            add_order_line(
                order,
                variant_id=uuid.uuid4(),
                description=f"Composant {i}",
                qty=Decimal(10),
                unit_price_mga=Decimal(100),
            )
        )
    submit_order_for_validation(order, user)
    validate_order(order, user)
    send_order(order, user)
    confirm_order(order, user)
    mark_order_in_transit(order, user)
    return order, created_lines


def test_receive_order_line_refuses_non_positive_qty(receiving_setup) -> None:
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        _order, (line,) = _order_in_transit(tenant, user, warehouse_id=warehouse.id)
        with pytest.raises(ValidationError):
            receive_order_line(
                line,
                qty_received_now=Decimal(0),
                quality_status=PurReceiptLine.QUALITY_CONFORME,
                user=user,
            )
        with pytest.raises(ValidationError):
            receive_order_line(
                line,
                qty_received_now=Decimal(-1),
                quality_status=PurReceiptLine.QUALITY_CONFORME,
                user=user,
            )


def test_receive_order_line_refuses_over_receiving_beyond_qty(receiving_setup) -> None:
    """RG-PUR-5 : l'ecart se mesure toujours contre la quantite commandee —
    jamais un sur-receptionnement silencieux (acceptance §5.6.7)."""
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        _order, (line,) = _order_in_transit(tenant, user, warehouse_id=warehouse.id)
        receive_order_line(
            line,
            qty_received_now=Decimal(6),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )
        with pytest.raises(ValidationError):
            receive_order_line(
                line,
                qty_received_now=Decimal(5),  # 6 + 5 = 11 > qty (10)
                quality_status=PurReceiptLine.QUALITY_CONFORME,
                user=user,
            )


def test_receive_order_line_refuses_when_order_not_yet_in_transit(receiving_setup) -> None:
    tenant, user, _warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        line = add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Composant",
            qty=Decimal(10),
            unit_price_mga=Decimal(100),
        )
        with pytest.raises(ValidationError):
            receive_order_line(
                line,
                qty_received_now=Decimal(1),
                quality_status=PurReceiptLine.QUALITY_CONFORME,
                user=user,
            )


def test_receive_order_line_refuses_invalid_quality_status(receiving_setup) -> None:
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        _order, (line,) = _order_in_transit(tenant, user, warehouse_id=warehouse.id)
        with pytest.raises(ValidationError):
            receive_order_line(
                line, qty_received_now=Decimal(1), quality_status="douteux", user=user
            )


def test_receive_order_line_refuses_without_a_configured_warehouse(receiving_setup) -> None:
    """Decision P2 (cahier Phase 3 §12.1) : une commande sans entrepot
    valide ne peut plus être "reçue" sans effet sur le stock physique —
    avant P2, `PurOrder.warehouse_id` était une simple métadonnée non
    vérifiée et la réception réussissait quand même, sans jamais toucher
    `stocks`."""
    tenant, user, _warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        _order, (line,) = _order_in_transit(tenant, user, warehouse_id=None)
        with pytest.raises(ValidationError):
            receive_order_line(
                line,
                qty_received_now=Decimal(1),
                quality_status=PurReceiptLine.QUALITY_CONFORME,
                user=user,
            )
        # Rien n'a été enregistré côté achat non plus (@transaction.atomic) :
        # ni la ligne de réception, ni la quantité reçue de la ligne.
        assert PurReceiptLine.objects.filter(order_line=line).count() == 0
        line.refresh_from_db()
        assert line.qty_received == Decimal(0)


def test_receive_order_line_creates_a_real_stock_move(receiving_setup) -> None:
    """Décision P2 : ferme la double comptabilité de quantité constatée
    par l'audit Phase 3 (§12.1/§3.1/§3.3) — une réception d'achat doit
    désormais se voir dans le quant de stock réel, pas seulement dans
    `PurOrderLine.qty_received`."""
    tenant, user, warehouse, internal_location = receiving_setup
    with use_tenant(tenant.id):
        _order, (line,) = _order_in_transit(tenant, user, warehouse_id=warehouse.id)
        receive_order_line(
            line,
            qty_received_now=Decimal(6),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )
        quant = StkQuant.objects.get(
            tenant=tenant, variant_id=line.variant_id, location=internal_location
        )
        assert quant.qty == Decimal(6)
        assert quant.value_mga == Decimal(6) * line.unit_price_mga

        # Une deuxième réception partielle s'ajoute au même quant.
        receive_order_line(
            line,
            qty_received_now=Decimal(4),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )
        quant.refresh_from_db()
        assert quant.qty == Decimal(10)


def test_receive_order_line_converts_purchase_uom_to_stock_uom(receiving_setup) -> None:
    """B1 (Phase 3 §12.2/§14, cahier ACH-3) : une ligne saisie dans une
    unite d'achat distincte de l'unite de stock du produit (ex. un carton
    de 12 pieces) doit produire un `StkQuant` dans l'unite de STOCK, avec
    la quantite CONVERTIE via le facteur declare — jamais la quantite
    d'achat brute."""
    tenant, user, warehouse, internal_location = receiving_setup
    with use_tenant(tenant.id):
        stock_uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        purchase_uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="CARTON", name="Carton", category=UnitOfMeasure.CATEGORY_COUNT
        )
        UnitConversion.objects.create(
            tenant=tenant, from_unit=purchase_uom, to_unit=stock_uom, factor=Decimal("12")
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Bouton", base_uom=stock_uom, reference="TPL-PUR-B1"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-B1"
        )

        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today(), warehouse_id=warehouse.id
        )
        line = add_order_line(
            order,
            variant_id=variant.id,
            description="Bouton (carton de 12)",
            qty=Decimal(10),
            unit_price_mga=Decimal(100),
            uom="CARTON",
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        send_order(order, user)
        confirm_order(order, user)
        mark_order_in_transit(order, user)

        receive_order_line(
            line,
            qty_received_now=Decimal(2),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )

        quant = StkQuant.objects.get(
            tenant=tenant, variant_id=variant.id, location=internal_location
        )
        # 2 cartons * facteur 12 = 24 pieces, dans l'unite de stock.
        assert quant.qty == Decimal(24)

        line.refresh_from_db()
        # `PurOrderLine.qty_received` reste dans l'unite d'ACHAT (cartons),
        # JAMAIS convertie — cf. sa docstring : RG-PUR-5 compare `qty` a
        # `qty_received` dans la MEME unite, un melange fausserait l'ecart.
        assert line.qty_received == Decimal(2)


def test_receive_order_line_refuses_when_conversion_factor_undeclared(receiving_setup) -> None:
    """Cahier ACH-3 : « le facteur de conversion est declare et verifie,
    jamais devine » — une unite d'achat differente de l'unite de stock du
    produit SANS `UnitConversion` declaree dans ce sens doit refuser la
    reception plutot que de deviner un facteur ou de melanger les
    unites."""
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        stock_uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC2", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Fermeture", base_uom=stock_uom, reference="TPL-PUR-B1-2"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-B1-2"
        )

        order = create_order(
            tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today(), warehouse_id=warehouse.id
        )
        line = add_order_line(
            order,
            variant_id=variant.id,
            description="Fermeture (sachet)",
            qty=Decimal(10),
            unit_price_mga=Decimal(100),
            uom="SACHET",  # jamais declaree via UnitConversion
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        send_order(order, user)
        confirm_order(order, user)
        mark_order_in_transit(order, user)

        with pytest.raises(ValidationError):
            receive_order_line(
                line,
                qty_received_now=Decimal(1),
                quality_status=PurReceiptLine.QUALITY_CONFORME,
                user=user,
            )
        # `@transaction.atomic` sur `receive_order_line` : rien n'est
        # persiste cote achat non plus (meme discipline que
        # `test_receive_order_line_refuses_without_a_configured_warehouse`).
        assert PurReceiptLine.objects.filter(order_line=line).count() == 0
        line.refresh_from_db()
        assert line.qty_received == Decimal(0)


def test_partial_receipt_updates_qty_received_and_order_state_across_two_receipts(
    receiving_setup,
) -> None:
    """Acceptance RG-PUR-5 : reception partielle sur une commande a 2
    lignes, en 2 evenements de reception successifs —
    in_transit -> partially_received -> received."""
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        order, (line1, line2) = _order_in_transit(tenant, user, lines=2, warehouse_id=warehouse.id)
        assert order.state == PurOrder.STATE_IN_TRANSIT

        # Premiere reception : seulement une partie de line1 -> partially_received.
        receive_order_line(
            line1,
            qty_received_now=Decimal(4),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
            notes="Premiere livraison",
        )
        line1.refresh_from_db()
        assert line1.qty_received == Decimal(4)
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_PARTIALLY_RECEIVED

        # Une deuxieme reception partielle ne doit pas lever (etat deja
        # partially_received, pas de nouvelle transition necessaire).
        receive_order_line(
            line1,
            qty_received_now=Decimal(6),
            quality_status=PurReceiptLine.QUALITY_NON_CONFORME,
            user=user,
        )
        line1.refresh_from_db()
        assert line1.qty_received == Decimal(10)
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_PARTIALLY_RECEIVED  # line2 pas encore recue

        # Reception complete de line2 -> toutes les lignes soldees -> received.
        receive_order_line(
            line2,
            qty_received_now=Decimal(10),
            quality_status=PurReceiptLine.QUALITY_SOUS_RESERVE,
            user=user,
        )
        line2.refresh_from_db()
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_RECEIVED

        # Historique complet : 3 evenements de reception, quality_status
        # conserve individuellement (jamais ecrase sur PurOrderLine).
        assert PurReceiptLine.objects.filter(order_line__order=order).count() == 3
        statuses = set(
            PurReceiptLine.objects.filter(order_line=line1).values_list("quality_status", flat=True)
        )
        assert statuses == {PurReceiptLine.QUALITY_CONFORME, PurReceiptLine.QUALITY_NON_CONFORME}


def test_first_receipt_on_in_transit_order_moves_at_least_to_partially_received(
    receiving_setup,
) -> None:
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        order, (line,) = _order_in_transit(tenant, user, warehouse_id=warehouse.id)
        assert order.state == PurOrder.STATE_IN_TRANSIT
        receive_order_line(
            line,
            qty_received_now=Decimal(1),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )
        order.refresh_from_db()
        assert order.state in (PurOrder.STATE_PARTIALLY_RECEIVED, PurOrder.STATE_RECEIVED)


def test_photo_document_ids_and_received_by_are_recorded(receiving_setup) -> None:
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        _order, (line,) = _order_in_transit(tenant, user, warehouse_id=warehouse.id)
        doc_ids = [uuid.uuid4(), uuid.uuid4()]
        receive_order_line(
            line,
            qty_received_now=Decimal(1),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
            photo_document_ids=doc_ids,
        )
        receipt = PurReceiptLine.objects.get(order_line=line)
        assert receipt.received_by_id == user.id
        assert set(receipt.photo_document_ids) == {str(doc_id) for doc_id in doc_ids}


def test_order_reception_variance_for_fully_and_partially_received_orders(
    receiving_setup,
) -> None:
    tenant, user, warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        order, (line1, line2) = _order_in_transit(tenant, user, lines=2, warehouse_id=warehouse.id)
        receive_order_line(
            line1,
            qty_received_now=Decimal(10),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )
        receive_order_line(
            line2,
            qty_received_now=Decimal(6),
            quality_status=PurReceiptLine.QUALITY_CONFORME,
            user=user,
        )
        order.refresh_from_db()
        assert order.state == PurOrder.STATE_PARTIALLY_RECEIVED

        rows = {row["line_id"]: row for row in order_reception_variance(order)}
        row1 = rows[line1.id]
        assert row1["qty_ordered"] == Decimal(10)
        assert row1["qty_received"] == Decimal(10)
        assert row1["variance"] == Decimal(0)
        assert row1["variance_pct"] == Decimal(0)

        row2 = rows[line2.id]
        assert row2["qty_ordered"] == Decimal(10)
        assert row2["qty_received"] == Decimal(6)
        assert row2["variance"] == Decimal(-4)
        assert row2["variance_pct"] == Decimal("-0.4")


def test_order_reception_variance_never_divides_by_zero(receiving_setup) -> None:
    """Garde `_ratio_or_none` (meme discipline qu'`accounting.services.
    budgets`/`reports`/`landed_costs`) : une ligne a `qty=0` ne doit jamais
    lever `ZeroDivisionError`."""
    tenant, _user, _warehouse, _internal_location = receiving_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Ligne nulle",
            qty=Decimal(0),
            unit_price_mga=Decimal(100),
        )
        rows = order_reception_variance(order)
        assert rows[0]["variance_pct"] is None
