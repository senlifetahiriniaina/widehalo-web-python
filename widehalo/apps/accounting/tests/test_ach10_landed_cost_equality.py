"""ACH-10 (L12-3) — le cout debarque unitaire restitue par le rapport
egale le cout du moteur de valorisation, a l'ariary pres.

Critere, mot pour mot : « Cout debarque unitaire restitue par le module
analytique egal au cout du moteur de valorisation, a l'ariary pres. »

**Correction de perimetre, et il faut la dire.** Le rapprochement
litteral — `AnFactReception.cout_debarque_unitaire_mga` contre le moteur
de valorisation — est une TAUTOLOGIE : ce champ est alimente
(`analytics/services/refresh.py:338`) par le retour litteral de
`stocks.services.public.get_variant_unit_cost`, c'est-a-dire par le
moteur lui-meme. Le test existant (`analytics/tests/test_refresh.py`) le
montre bien malgre lui : il pose une couche a 1200 et assert 1200.

Le rapprochement qui a un sens oppose deux calculs REELLEMENT
independants : le cout debarque CALCULE par
`accounting.services.landed_costs.landed_cost_report` (valeur d'achat +
quote-part de frais, divisee par la quantite declaree) face au cout
VALORISE que le moteur detient apres `apply_landed_cost_to_valuation`.
C'est ce que ces tests verifient.

**Et sa limite, testee plutot que passee sous silence.** L'egalite tient
quand rien n'a ete consomme entre la reception et la finalisation du lot.
Des qu'une partie du stock est sortie, `apply_landed_cost_to_valuation`
repartit les frais « au prorata de la QUANTITE RESTANTE » (simplification
assumee, cf. sa docstring) : les unites deja vendues n'en portent aucune
part, et les unites restantes les absorbent toutes. Les deux chiffres
divergent alors legitimement — le rapport decrit la declaration en
douane, le moteur decrit ce qui reste en stock. Le second test le fige.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccLandedCostBatch
from apps.accounting.services.landed_costs import (
    add_cost_component,
    add_landed_cost_line,
    create_landed_cost_batch,
    finalize_batch,
    landed_cost_report,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.public import get_variant_unit_cost
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db

RECEIVED_QTY = Decimal(100)
PURCHASE_UNIT_COST = Decimal(1000)
PURCHASE_VALUE = RECEIVED_QTY * PURCHASE_UNIT_COST
FREIGHT = Decimal(20000)


@pytest.fixture
def landed_setup():
    tenant = Tenant.objects.create(code="ACH10", name="ACH-10 Landed Cost Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-LC", name="Entrepot import")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="LC1",
            name="Rayon LC1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="LCF",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="LCC",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        variant_id = uuid.uuid4()
        validate_move(
            create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=RECEIVED_QTY,
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 4, 1),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=PURCHASE_UNIT_COST,
            )
        )
        return tenant, internal, client, variant_id


def _batch_for(tenant, variant_id):
    batch = create_landed_cost_batch(
        tenant=tenant,
        label="Import conteneur",
        date=dt.date(2026, 4, 2),
        allocation_method=AccLandedCostBatch.METHOD_BY_VALUE,
    )
    add_landed_cost_line(
        batch,
        description="Tissu importe",
        qty=RECEIVED_QTY,
        purchase_value_mga=PURCHASE_VALUE,
        variant_id=variant_id,
    )
    add_cost_component(batch, label="Fret maritime", amount_mga=FREIGHT)
    return batch


def test_the_reported_landed_unit_cost_equals_the_valuation_engine(landed_setup) -> None:
    """Les deux cotes sont calcules independamment : le rapport divise
    (valeur d'achat + quote-part de frais) par la quantite declaree ; le
    moteur agrege ses couches apres revalorisation. Ils doivent tomber sur
    le meme ariary."""
    tenant, _internal, _client, variant_id = landed_setup
    with use_tenant(tenant.id):
        batch = _batch_for(tenant, variant_id)

        # Avant finalisation, le moteur ne connait que le cout d'achat.
        assert get_variant_unit_cost(tenant, variant_id) == PURCHASE_UNIT_COST

        report_before = landed_cost_report(batch)
        reported_unit_cost = report_before[0]["landed_unit_cost_mga"]
        # (100 000 + 20 000) / 100.
        assert reported_unit_cost == Decimal(1200)

        finalize_batch(batch)

        assert get_variant_unit_cost(tenant, variant_id) == reported_unit_cost
        # Le rapport ne bouge pas a la finalisation : c'est bien deux
        # calculs distincts qui convergent, pas l'un qui lit l'autre.
        assert landed_cost_report(batch)[0]["landed_unit_cost_mga"] == reported_unit_cost


def test_the_equality_breaks_once_part_of_the_stock_has_left(landed_setup) -> None:
    """Limite documentee, rendue opposable.

    `apply_landed_cost_to_valuation` repartit les frais au prorata de la
    quantite RESTANTE. Si 40 des 100 unites sont deja sorties, les 60
    restantes absorbent la totalite du fret : le moteur affiche
    (60 000 + 20 000) / 60 = 1333,33 la ou le rapport affiche toujours
    1200. Les deux ont raison dans leur perimetre — le rapport decrit la
    declaration, le moteur ce qui reste en stock — et un lecteur qui les
    croirait interchangeables se tromperait."""
    tenant, internal, client, variant_id = landed_setup
    with use_tenant(tenant.id):
        batch = _batch_for(tenant, variant_id)

        validate_move(
            create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=Decimal(40),
                uom="pc",
                location_from=internal,
                location_to=client,
                date=dt.date(2026, 4, 3),
                move_type=StkMove.TYPE_LIVRAISON,
            )
        )
        finalize_batch(batch)

        reported = landed_cost_report(batch)[0]["landed_unit_cost_mga"]
        valued = get_variant_unit_cost(tenant, variant_id)

        assert reported == Decimal(1200)
        # (100 000 - 40 000 + 20 000) / 60.
        assert valued is not None
        assert valued.quantize(Decimal("0.01")) == Decimal("1333.33")
        assert valued != reported


def test_a_falsified_freight_amount_breaks_the_equality(landed_setup) -> None:
    """Sans ce test, l'egalite pourrait tenir par hasard. On ajoute un
    second composant de frais APRES avoir lu le rapport : le moteur, lui,
    recevra la quote-part complete a la finalisation, et les deux chiffres
    doivent alors differer."""
    tenant, _internal, _client, variant_id = landed_setup
    with use_tenant(tenant.id):
        batch = _batch_for(tenant, variant_id)
        stale_report = landed_cost_report(batch)[0]["landed_unit_cost_mga"]

        add_cost_component(batch, label="Assurance", amount_mga=Decimal(5000))
        finalize_batch(batch)

        fresh_report = landed_cost_report(batch)[0]["landed_unit_cost_mga"]
        assert fresh_report == Decimal(1250)  # (100 000 + 25 000) / 100
        assert get_variant_unit_cost(tenant, variant_id) == fresh_report
        assert get_variant_unit_cost(tenant, variant_id) != stale_report
