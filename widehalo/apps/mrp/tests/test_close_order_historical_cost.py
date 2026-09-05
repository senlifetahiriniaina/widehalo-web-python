"""PRD-9 (L12-2) — le cout reel d'un ordre cloture est valorise au CUMP
A LA DATE D'EFFET de chaque consommation, jamais a celui du jour de la
cloture.

Critere, mot pour mot : « Le cout reel d'un ordre cloture est egal a la
somme des consommations valorisees au CUMP a leur date d'effet [...] a
l'ariary pres. »

**Ce que ces tests ferment, et pourquoi le critere etait faux avant.**
`close_order` resolvait les couts par `stocks.services.public.
get_variant_unit_cost`, dont la docstring dit elle-meme « cout unitaire
COURANT ». C'est le CUMP au moment de la CLOTURE. Sur un ordre dont les
consommations s'etalent et dont le CUMP bouge entre-temps — une reception
plus chere, par exemple — le cout de revient de l'ordre etait celui d'un
approvisionnement qui n'avait pas servi a le fabriquer.

Le scenario ci-dessous est construit pour que les deux valeurs DIFFERENT :
sans la correction, le premier test echoue avec 30 000 au lieu de 10 000.
Sans cette divergence, il passerait aussi sur l'ancien code et ne
prouverait rien.

La date d'effet elle-meme n'etait enregistree nulle part : ni
`consume_component` ni `record_component_consumption` ne la posaient.
`MrpOrderComponent.consumed_at` la porte desormais.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.costing import consume_component
from apps.mrp.services.orders import (
    close_order,
    confirm_order,
    create_order,
    finish_order,
    reserve_order,
    send_to_quality_control,
    start_order,
)
from apps.mrp.services.transformation import record_component_consumption
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db

# Le CUMP passe de 500 a 1500 entre la consommation et la cloture : c'est
# tout l'objet de ces tests, et c'est ce qui les rend capables d'echouer.
CONSUMPTION_DATE = dt.date(2026, 3, 5)
CUMP_AT_CONSUMPTION = Decimal(500)
QTY_CONSUMED = Decimal(20)


@pytest.fixture
def historical_cost_setup():
    """Ordre pret a clore, dont le composant est couvert par de VRAIS
    mouvements de stock — le rejeu lit les `StkMove`, une couche fabriquee
    directement par une factory ne lui dirait rien."""
    tenant = Tenant.objects.create(code="MRP-HCOST", name="MRP Historical Cost Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="hcost@example.com", password="Str0ngPassw0rd!23")
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-HC", name="Atelier")
        warehouse = create_warehouse(tenant=tenant, code="WH-HC", name="Entrepot")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="HC1",
            name="Rayon HC1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="HCF",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        component_template_id = uuid.uuid4()
        component_variant_id = uuid.uuid4()

        # Reception AVANT la consommation : c'est ce cout-la qui doit servir.
        validate_move(
            create_move(
                tenant=tenant,
                variant_id=component_variant_id,
                qty=Decimal(100),
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 3, 1),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=CUMP_AT_CONSUMPTION,
            )
        )

        bom = create_bom(tenant=tenant, code="BOM-HC", product_template_id=uuid.uuid4())
        add_bom_line(
            bom,
            component_template_id=component_template_id,
            component_variant_id=component_variant_id,
            qty=Decimal(2),
        )
        activate_bom(bom)
        order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=Decimal(10))
        confirm_order(order, user)
        reserve_order(order, user)
        start_order(order, user)
        send_to_quality_control(order, user)
        return tenant, user, order, internal, supplier, component_variant_id


def _later_and_dearer_reception(tenant, *, variant_id, supplier, internal) -> None:
    """Deplace le CUMP courant a 1500 APRES la consommation : (100 x 500 +
    100 x 2500) / 200. Sans ce mouvement, l'ancien et le nouveau code
    donneraient le meme chiffre."""
    validate_move(
        create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(100),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 3, 10),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal(2500),
        )
    )


def test_close_order_values_consumption_at_the_cump_of_its_effective_date(
    historical_cost_setup,
) -> None:
    """LE test du critere. Avant L12-2 il donnait 30 000 (20 x 1500, le
    CUMP du jour de la cloture) la ou le critere exige 10 000 (20 x 500,
    celui de la date d'effet)."""
    tenant, user, order, internal, supplier, variant_id = historical_cost_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        consume_component(component, qty_consumed=QTY_CONSUMED, date=CONSUMPTION_DATE)

        _later_and_dearer_reception(
            tenant, variant_id=variant_id, supplier=supplier, internal=internal
        )

        finish_order(order, user, qty_produced=Decimal(10))
        closed = close_order(order, user)

        assert closed.cost_material_mga == QTY_CONSUMED * CUMP_AT_CONSUMPTION
        assert closed.cost_material_mga == Decimal(10000)
        # Et surtout : PAS le CUMP courant, qui vaut desormais 1500.
        assert closed.cost_material_mga != QTY_CONSUMED * Decimal(1500)


def test_the_consumption_records_its_effective_date(historical_cost_setup) -> None:
    """La date d'effet n'etait enregistree nulle part avant L12-2 : sans
    elle, aucune valorisation historique n'est possible, quel que soit le
    moteur de cout."""
    tenant, _user, order, _internal, _supplier, _variant_id = historical_cost_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        assert component.consumed_at is None

        consume_component(component, qty_consumed=QTY_CONSUMED, date=CONSUMPTION_DATE)
        component.refresh_from_db()
        assert component.consumed_at == CONSUMPTION_DATE


def test_the_transformation_path_records_it_too(historical_cost_setup) -> None:
    """Deux chemins de declaration coexistent (`consume_component` et
    `record_component_consumption`). Si un seul posait la date, la cloture
    retomberait silencieusement au CUMP courant pour l'autre."""
    tenant, _user, order, _internal, _supplier, _variant_id = historical_cost_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        record_component_consumption(
            component,
            lot_name="LOT-HC-1",
            qty_consumed=QTY_CONSUMED,
            date=CONSUMPTION_DATE,
        )
        component.refresh_from_db()
        assert component.consumed_at == CONSUMPTION_DATE


def test_a_component_without_effective_date_falls_back_to_the_current_cump(
    historical_cost_setup,
) -> None:
    """Repli DECLARE pour les composants anterieurs a `consumed_at` :
    inventer une date serait pire. On laisse donc la date nulle et on
    verifie que le cout est bien celui du CUMP courant — 1500 ici, et non
    zero : ecarter le composant du cout le sous-evaluerait en silence."""
    tenant, user, order, internal, supplier, variant_id = historical_cost_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        consume_component(component, qty_consumed=QTY_CONSUMED, date=CONSUMPTION_DATE)
        # Simule un composant consomme avant l'existence du champ.
        order.components.filter(id=component.id).update(consumed_at=None)

        _later_and_dearer_reception(
            tenant, variant_id=variant_id, supplier=supplier, internal=internal
        )

        finish_order(order, user, qty_produced=Decimal(10))
        closed = close_order(order, user)

        assert closed.cost_material_mga == QTY_CONSUMED * Decimal(1500)


def test_the_fallback_is_logged_when_no_history_exists_at_that_date(
    historical_cost_setup, caplog
) -> None:
    """Un composant dont la date d'effet PRECEDE tout mouvement : le rejeu
    ne trouve rien. Le cout retombe sur le CUMP courant plutot que de
    compter pour zero, et le dit — un repli silencieux est exactement ce
    qui rend un defaut invisible."""
    tenant, user, order, _internal, _supplier, _variant_id = historical_cost_setup
    with use_tenant(tenant.id):
        component = order.components.first()
        # Anterieure a la reception du 1er mars : aucun stock a cette date.
        consume_component(component, qty_consumed=QTY_CONSUMED, date=dt.date(2026, 1, 15))

        finish_order(order, user, qty_produced=Decimal(10))
        with caplog.at_level("WARNING"):
            closed = close_order(order, user)

        assert closed.cost_material_mga == QTY_CONSUMED * CUMP_AT_CONSUMPTION
        assert any("repli sur le CUMP courant" in record.message for record in caplog.records)
