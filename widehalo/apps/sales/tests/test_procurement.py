"""RG-SAL-3 (§5.5.3) : qualification d'origine par ligne, declenchee par
`confirm_order` depuis S3 (cf. plan, sous-sequencement `sales`).
`test_acceptance_1_order_confirmation_qualifies_all_three_line_origins`
exerce nommement le test d'acceptance §5.5.8 n°1 du CDC, avec la
deviation documentee et actee dans le plan (section "Module `sales`",
decisions de sequencement RG-SAL-3) : le CDC original envisage un document
reel pour les trois branches ("un ordre de fabrication pour la ligne a
produire, une demande d'achat pour la ligne a acheter, et une reservation
pour la ligne en stock"), mais seul `purchase`/`stocks` livre pourra
produire les deux derniers documents reels — ces deux modules n'existent
pas encore dans cet ordre de Lot 2 (SALES est sequence avant eux). Les
branches "sur stock"/"a acheter" sont donc verifiees ici comme
correctement qualifiees et marquees en attente du module correspondant,
pas comme un document reel genere."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.services.bom import activate_bom, create_bom
from apps.mrp.tests.factories import MrpWorkshopFactory
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.sales.services.orders import add_order_line, confirm_order, create_order
from apps.sales.services.procurement import qualify_and_process_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def procurement_setup():
    tenant = Tenant.objects.create(code="SALES-PROC", name="Sales Procurement Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="sales-proc@example.com", password="Str0ngPassw0rd!23"
        )
        partner = PartnerFactory(tenant=tenant)
        return tenant, user, partner


def test_acceptance_1_order_confirmation_qualifies_all_three_line_origins(
    procurement_setup,
) -> None:
    tenant, user, partner = procurement_setup
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="U", name="Unite", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="Polo", base_uom=uom, reference="TPL-PROC-0001"
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PROC-0001"
        )
        product_template_id = template.id
        variant_id = variant.id
        bom = create_bom(tenant=tenant, code="BOM-ACC-1", product_template_id=product_template_id)
        activate_bom(bom)
        MrpWorkshopFactory(tenant=tenant)

        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        production_line = add_order_line(
            order,
            variant_id=variant_id,
            description="Article a produire",
            qty=Decimal(3),
            unit_price=Decimal(1000),
            source=SalesOrderLine.SOURCE_PRODUCTION,
        )
        stock_line = add_order_line(
            order,
            description="Article sur stock",
            qty=Decimal(2),
            unit_price=Decimal(500),
            is_custom=True,
            source=SalesOrderLine.SOURCE_STOCK,
        )
        purchase_line = add_order_line(
            order,
            description="Article a acheter",
            qty=Decimal(1),
            unit_price=Decimal(2000),
            is_custom=True,
            source=SalesOrderLine.SOURCE_ACHAT,
        )

        confirmed = confirm_order(order, user)
        assert confirmed.state == SalesOrder.STATE_CONFIRMED

        # Branche "a produire" : REELLE, verifiee sans qualification — un
        # vrai MrpOrder est cree et rattache a la ligne.
        production_line.refresh_from_db()
        assert production_line.mrp_order_id is not None
        assert production_line.qty_to_produce == Decimal(3)

        # Branches "sur stock"/"a acheter" : STUBEES (deviation assumee,
        # cf. docstring module) — aucun document reel n'est genere, la
        # ligne est seulement marquee en attente du module correspondant.
        stock_line.refresh_from_db()
        purchase_line.refresh_from_db()
        assert stock_line.mrp_order_id is None
        assert purchase_line.mrp_order_id is None
        assert purchase_line.purchase_order_line_id is None

        summary = qualify_and_process_order(order, user)
        assert str(production_line.id) in summary["produced"]
        assert str(stock_line.id) in summary["pending_stock"]
        assert str(purchase_line.id) in summary["pending_purchase"]


def test_production_line_without_active_bom_needs_manual_production(procurement_setup) -> None:
    tenant, user, partner = procurement_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Article sans nomenclature active",
            qty=Decimal(1),
            unit_price=Decimal(1000),
            source=SalesOrderLine.SOURCE_PRODUCTION,
        )

        confirm_order(order, user)

        line.refresh_from_db()
        assert line.mrp_order_id is None
        summary = qualify_and_process_order(order, user)
        assert str(line.id) in summary["needs_manual_production"]


def test_custom_production_line_without_variant_needs_manual_production(
    procurement_setup,
) -> None:
    tenant, user, partner = procurement_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            description="Article sur mesure, hors catalogue",
            qty=Decimal(1),
            unit_price=Decimal(1000),
            is_custom=True,
            source=SalesOrderLine.SOURCE_PRODUCTION,
        )

        confirm_order(order, user)

        line.refresh_from_db()
        assert line.mrp_order_id is None
        summary = qualify_and_process_order(order, user)
        assert str(line.id) in summary["needs_manual_production"]


def test_qualify_and_process_order_is_not_run_on_blocked_order(procurement_setup) -> None:
    """RG-SAL-4 x RG-SAL-3 : une commande bloquee pour depassement de
    credit ne doit jamais declencher de qualification RG-SAL-3 — cf.
    garde explicite dans `confirm_order` (qui n'appelle
    `qualify_and_process_order` qu'apres une transition `confirm` reussie)."""
    tenant, user, _partner = procurement_setup
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant, credit_limit_mga=Decimal("5000"))
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        line = add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Article a produire",
            qty=Decimal(1),
            unit_price=Decimal(10000),
            source=SalesOrderLine.SOURCE_PRODUCTION,
        )

        blocked = confirm_order(order, user)
        assert blocked.state == SalesOrder.STATE_BLOCKED

        line.refresh_from_db()
        assert line.mrp_order_id is None
