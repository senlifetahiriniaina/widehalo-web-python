"""RG-STK-2 (valorisation) : consommation de plusieurs couches
`StkValuationLayer`, verifiee a la main (meme rigueur que l'exemple A17
verifie a la main pour les couts d'approche, `accounting`) — sous les deux
methodes disponibles depuis la decision P3 (cahier Phase 3 §12.4) : CUMP
(`test_cmp_consumption_across_multiple_layers_hand_verified`, methode par
defaut depuis P3) et FIFO
(`test_fifo_consumption_across_multiple_layers_hand_verified`, toujours
selectionnable explicitement, cf. cahier §11.1)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkValuationLayer
from apps.stocks.services.moves import VALUATION_METHOD_FIFO, create_move, validate_move
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def valuation_setup():
    tenant = Tenant.objects.create(code="STK-VAL-T", name="Stocks Valuation Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        return tenant, internal, supplier, client


def test_fifo_consumption_across_multiple_layers_hand_verified(valuation_setup) -> None:
    """Calcul a la main :
    - Reception n1 : 10 unites a 1000 MGA/u -> couche 1 (valeur 10 000).
    - Reception n2 : 5 unites a 1200 MGA/u -> couche 2 (valeur 6 000).
    - Stock total avant consommation : 15 unites, valeur 16 000 MGA.
    - Livraison de 12 unites (> couche 1 seule) :
        * couche 1 entierement consommee : 10 u, valeur 10 000.
        * couche 2 partiellement consommee : 2 u sur 5, valeur 2*1200 = 2 400.
        * valeur totale sortie : 10 000 + 2 400 = 12 400 MGA.
        * cout moyen du mouvement de sortie : 12 400 / 12 = 1033.3333... MGA/u.
    - Couches apres consommation :
        * couche 1 : remaining_qty = 0, remaining_value_mga = 0.
        * couche 2 : remaining_qty = 3, remaining_value_mga = 6 000 - 2 400 = 3 600.
    - Valeur totale de stock restante : 0 + 3 600 = 3 600 MGA, pour 3 unites
      restantes (coherent avec le cout unitaire de la couche 2 : 3*1200=3600).
    """
    tenant, internal, supplier, client = valuation_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        reception_1 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception_1)

        reception_2 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(5),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 2),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1200"),
        )
        validate_move(reception_2)

        layers_before = StkValuationLayer.objects.filter(variant_id=variant_id).order_by("date")
        assert list(layers_before.values_list("qty", "unit_cost_mga", "value_mga")) == [
            (Decimal("10.0000"), Decimal("1000.0000"), Decimal("10000.0000")),
            (Decimal("5.0000"), Decimal("1200.0000"), Decimal("6000.0000")),
        ]

        livraison = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 3),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        validate_move(livraison, valuation_method=VALUATION_METHOD_FIFO)
        livraison.refresh_from_db()

        # `value_mga` (la valeur EXACTEMENT sortie du stock) est l'assertion
        # qui compte pour RG-STK-2 — `unit_cost_mga` (12400/12 = 1033.33...,
        # non decimal exact) reste informatif, arrondi par la base a 4
        # decimales, jamais utilise pour deriver `value_mga` (cf. docstring
        # `_apply_quant_delta`) : verifie seulement qu'il est proche de la
        # division theorique, sans exiger un arrondi bit-a-bit identique.
        assert livraison.value_mga == Decimal("12400.0000")
        assert abs(livraison.unit_cost_mga - Decimal("12400") / Decimal(12)) < Decimal("0.001")

        layer_1, layer_2 = StkValuationLayer.objects.filter(variant_id=variant_id).order_by("date")
        assert layer_1.remaining_qty == Decimal("0.0000")
        assert layer_1.remaining_value_mga == Decimal("0.0000")
        assert layer_2.remaining_qty == Decimal("3.0000")
        assert layer_2.remaining_value_mga == Decimal("3600.0000")

        total_remaining_value = sum(
            (
                StkValuationLayer.objects.filter(variant_id=variant_id).values_list(
                    "remaining_value_mga", flat=True
                )
            ),
            Decimal(0),
        )
        assert total_remaining_value == Decimal("3600.0000")


def test_cmp_consumption_across_multiple_layers_hand_verified(valuation_setup) -> None:
    """Meme scenario que le test FIFO ci-dessus, mais sous CUMP (methode
    par defaut depuis la decision P3) — calcul a la main :
    - Reception n1 : 10 unites a 1000 MGA/u -> couche 1 (valeur 10 000).
    - Reception n2 : 5 unites a 1200 MGA/u -> couche 2 (valeur 6 000).
    - Stock total avant consommation : 15 unites, valeur 16 000 MGA —
      cout moyen pondere du pool : 16000/15 = 1066,6666... MGA/u.
    - Livraison de 12 unites, repartition PROPORTIONNELLE (fraction =
      12/15 = 0,8) — chaque couche perd exactement 80% de sa propre
      quantite ET de sa propre valeur, jamais l'ordre d'entree qui
      redonnerait du FIFO :
        * couche 1 : 10*0,8 = 8 unites, 10 000*0,8 = 8 000 MGA retires.
        * couche 2 (derniere couche active, absorbe le reliquat exact) :
          12-8 = 4 unites, 12800-8000 = 4 800 MGA retires.
        * valeur totale sortie : 8 000 + 4 800 = 12 800 MGA (= 12 * cout
          moyen pondere 1066,6666..., a l'ariary pres apres arrondi).
    - Couches apres consommation, chacune conservant SON PROPRE cout
      unitaire d'origine (contrairement au FIFO, aucune couche n'est
      entierement epuisee ici) :
        * couche 1 : remaining_qty = 2, remaining_value_mga = 2 000
          (cout unitaire toujours 1000 — 2*1000=2000).
        * couche 2 : remaining_qty = 1, remaining_value_mga = 1 200
          (cout unitaire toujours 1200 — 1*1200=1200).
    - Valeur totale de stock restante : 2 000 + 1 200 = 3 200 MGA, pour
      3 unites restantes — coherent avec 16 000 - 12 800 = 3 200."""
    tenant, internal, supplier, client = valuation_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        reception_1 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception_1)

        reception_2 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(5),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 2),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1200"),
        )
        validate_move(reception_2)

        livraison = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 3),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        validate_move(livraison)  # CUMP est le defaut depuis la decision P3
        livraison.refresh_from_db()

        assert livraison.value_mga == Decimal("12800.0000")
        assert abs(livraison.unit_cost_mga - Decimal("12800") / Decimal(12)) < Decimal("0.001")

        layer_1, layer_2 = StkValuationLayer.objects.filter(variant_id=variant_id).order_by("date")
        assert layer_1.remaining_qty == Decimal("2.0000")
        assert layer_1.remaining_value_mga == Decimal("2000.0000")
        assert layer_2.remaining_qty == Decimal("1.0000")
        assert layer_2.remaining_value_mga == Decimal("1200.0000")

        internal_quant = internal.quants.get(variant_id=variant_id)
        assert internal_quant.value_mga == Decimal("3200.0000")


def test_stock_value_equals_sum_of_remaining_layers_after_sequence(valuation_setup) -> None:
    """Sequence receive/receive/consume/receive/consume, verifie que la
    valeur totale de stock (deduite de `StkQuant.value_mga` a l'emplacement
    interne) egale la somme des `remaining_value_mga` de toutes les
    couches du variant — condition d'acceptance §5.8.7 n°2."""
    tenant, internal, supplier, client = valuation_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        for qty, cost in [(Decimal(10), Decimal("500")), (Decimal(6), Decimal("800"))]:
            move = create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=qty,
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 1, 1),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=cost,
            )
            validate_move(move)

        consume_1 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(4),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 2),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        validate_move(consume_1)

        receive_3 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(2),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 1, 3),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("900"),
        )
        validate_move(receive_3)

        consume_2 = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 1, 4),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        validate_move(consume_2)

        total_remaining_value = sum(
            StkValuationLayer.objects.filter(variant_id=variant_id).values_list(
                "remaining_value_mga", flat=True
            ),
            Decimal(0),
        )
        internal_quant = internal.quants.get(variant_id=variant_id)
        assert internal_quant.value_mga == total_remaining_value
