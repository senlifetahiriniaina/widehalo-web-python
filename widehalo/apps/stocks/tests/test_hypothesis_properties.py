"""Tests de proprietes (couche 13 du CDC, §8) : RG-STK-1 (double entree,
§5.8.7 acceptance test n1) et RG-STK-2 (valorisation FIFO, §5.8.7
acceptance test n2) verifies sur des mouvements/operations generes
arbitrairement par Hypothesis — meme patron que
`apps.accounting.tests.test_hypothesis_properties` (1000 exemples, chaque
exemple cree son propre tenant/entrepot/emplacements via `uuid4` pour
eviter le health check `function_scoped_fixture`, marque
`@pytest.mark.slow` — exclu du run standard, cf. `addopts = "-ra -m 'not
slow'"` dans `pyproject.toml`, execute explicitement via
`pytest -m slow`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.db.models import Sum
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkQuant, StkValuationLayer
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.negative_stock import grant_negative_stock_exception
from apps.stocks.services.quants import get_quant
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db

# Amplitude compatible avec DecimalField(max_digits=18, decimal_places=4) —
# meme raisonnement que `_AMOUNT` dans `apps.accounting.tests.
# test_hypothesis_properties` : on reste tres loin du plafond, montants
# strictement positifs (RG-STK-1 : `qty` d'un `StkMove` est TOUJOURS > 0).
_QTY = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)
_COST = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("1000"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)


def _stock_setup() -> tuple[Tenant, list[StkLocation], list[uuid.UUID]]:
    """Cree un tenant/entrepot/emplacements unique par exemple Hypothesis
    (meme raisonnement `uuid4` que `accounting`) — un petit pool fixe de 5
    emplacements (2 internes, 3 virtuels de types differents) et 3
    variants, reutilise par tous les mouvements de l'exemple courant."""
    tenant = Tenant.objects.create(
        code=f"HYP-STK-{uuid.uuid4().hex[:12]}", name="Hypothesis Stocks Tenant"
    )
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH", name="Entrepot Hypothesis")
        locations = [
            create_location(
                tenant=tenant,
                warehouse=warehouse,
                code="INT1",
                name="Interne 1",
                type=StkLocation.TYPE_INTERNE,
            ),
            create_location(
                tenant=tenant,
                warehouse=warehouse,
                code="INT2",
                name="Interne 2",
                type=StkLocation.TYPE_INTERNE,
            ),
            create_location(
                tenant=tenant,
                warehouse=warehouse,
                code="FRS",
                name="Fournisseur",
                type=StkLocation.TYPE_FOURNISSEUR,
            ),
            create_location(
                tenant=tenant,
                warehouse=warehouse,
                code="CLI",
                name="Client",
                type=StkLocation.TYPE_CLIENT,
            ),
            create_location(
                tenant=tenant,
                warehouse=warehouse,
                code="PROD",
                name="Production",
                type=StkLocation.TYPE_PRODUCTION,
            ),
        ]
        variant_ids = [uuid.uuid4() for _ in range(3)]
    return tenant, locations, variant_ids


# (index de variant, quantite, (index emplacement origine, index emplacement
# destination distinct)) — le filtre `t[0] != t[1]` garantit une paire
# d'emplacements toujours distincte, meme garde que
# `create_move`/le CHECK DB `stk_move_from_ne_to`.
_LOCATION_PAIR = st.tuples(
    st.integers(min_value=0, max_value=4), st.integers(min_value=0, max_value=4)
).filter(lambda pair: pair[0] != pair[1])
_MOVE_SPEC = st.tuples(st.integers(min_value=0, max_value=2), _QTY, _LOCATION_PAIR)


@pytest.mark.slow
@given(move_specs=st.lists(_MOVE_SPEC, min_size=1, max_size=5))
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_rg_stk_1_algebraic_sum_is_always_zero_per_variant(
    move_specs: list[tuple[int, Decimal, tuple[int, int]]],
) -> None:
    """RG-STK-1 (§5.8.7 acceptance test n1) : pour un nombre arbitraire de
    mouvements de stock valides (quantite/emplacements/variant aleatoires,
    emplacements virtuels inclus), la somme algebrique de `StkQuant.qty`
    sur TOUS les emplacements (internes ET virtuels) doit toujours etre
    exactement nulle, pour chaque variant — "aucune quantite n'apparait ni
    ne disparait sans contrepartie" (CDC §5.8), verifie ici independamment
    de la logique de valorisation (RG-STK-2, teste separement ci-dessous).

    **Resolution de la tension RG-STK-10 (ST7) vs ce test (ST2)** : ce
    test genere des mouvements aleatoires SANS jamais tenir compte de la
    quantite reellement disponible a la source (a la difference du test
    RG-STK-2 ci-dessous, qui plafonne deliberement ses consommations a
    `available`) — c'est le point meme de ce test : verifier l'invariant
    de somme algebrique nulle QUELLE QUE SOIT la sequence de mouvements,
    y compris des sequences qui epuiseraient un emplacement interne.
    Depuis l'ajout de la garde RG-STK-10 dans `validate_move` (ST7,
    interdiction du stock negatif par defaut cote emplacement interne),
    une partie de ces mouvements aleatoires leverait desormais
    `ValidationError` sans une exception active. Plutot que de restreindre
    le generateur Hypothesis (ce qui reduirait la couverture reelle de ce
    test de propriete — RG-STK-1 porte sur TOUS les emplacements, internes
    ET virtuels, la negativite d'un emplacement interne n'est pas hors de
    son perimetre de verification), une exception RG-STK-10 est accordee
    en amont pour chacun des 3 variants de l'exemple courant — RG-STK-1
    (double entree) et RG-STK-10 (stock negatif) sont deux regles
    INDEPENDANTES : la premiere porte sur la coherence algebrique de
    TOUTE sequence de mouvements valides, la seconde sur la LICEITE d'un
    mouvement donne avant qu'il ne soit valide — accorder l'exception ne
    change rien a ce que ce test verifie reellement (la somme algebrique),
    seulement a ce qui est AUTORISE a s'executer en amont."""
    tenant, locations, variant_ids = _stock_setup()
    with use_tenant(tenant.id):
        authorizer = UserFactory()
        for variant_id in variant_ids:
            grant_negative_stock_exception(
                tenant=tenant,
                variant_id=variant_id,
                authorized_by=authorizer,
                reason="Exception de test — proprietes RG-STK-1 (Hypothesis)",
            )
        move_date = dt.date(2026, 1, 1)
        for variant_idx, qty, (from_idx, to_idx) in move_specs:
            move = create_move(
                tenant=tenant,
                variant_id=variant_ids[variant_idx],
                qty=qty,
                uom="pc",
                location_from=locations[from_idx],
                location_to=locations[to_idx],
                date=move_date,
                move_type=StkMove.TYPE_AJUSTEMENT,
            )
            validate_move(move)

        for variant_id in variant_ids:
            total = StkQuant.objects.filter(tenant=tenant, variant_id=variant_id).aggregate(
                total=Sum("qty")
            )["total"] or Decimal(0)
            assert total == Decimal(0)


# 500 operations receive/consume EXACTEMENT (min_size == max_size) par
# exemple — "500 operations FIFO" du CDC (§5.8.7 acceptance test n2) est
# ici un compte exact d'operations dans CHAQUE exemple genere, pas une
# moyenne sur plusieurs exemples (a la difference de RG-STK-1 ci-dessus,
# ou "1000 mouvements" se lit comme 1000 EXEMPLES, convention deja etablie
# par `accounting`). `max_examples` reduit a 10 (au lieu de 1000) : chaque
# exemple execute deja 500 operations reelles en base (create+validate),
# soit ~5000 mouvements de stock au total sur l'ensemble du test — cout
# largement superieur a un test a 1000 exemples "legers" comme RG-STK-1.
_RECEIVE_OR_CONSUME = st.tuples(st.booleans(), _QTY, _COST)


@pytest.mark.slow
@given(operations=st.lists(_RECEIVE_OR_CONSUME, min_size=500, max_size=500))
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_rg_stk_2_stock_value_equals_sum_of_remaining_layers(
    operations: list[tuple[bool, Decimal, Decimal]],
) -> None:
    """RG-STK-2 (§5.8.7 acceptance test n2) : apres 500 operations FIFO
    (reception/consommation) sur un seul variant, la valeur de stock (le
    `value_mga` du quant a l'emplacement interne) doit etre EXACTEMENT
    egale a la somme des `remaining_value_mga` de toutes les couches de
    valorisation du variant — aucune tolerance d'arrondi (meme rigueur que
    le test d'explosion de nomenclature `mrp`, T9).

    Une "consommation" tiree par Hypothesis est plafonnee a la quantite
    reellement disponible (`available`, suivie ici cote test) : consommer
    plus que le stock reellement possede ferait basculer
    `_consume_fifo_layers` sur son filet de secours a cout fourni par
    l'appelant (cf. docstring `services/moves.py`) — comportement
    delibrement HORS invariant RG-STK-2 (c'est litteralement du stock
    negatif, RG-STK-10, hors perimetre ST2) : le plafonnage ici garantit
    que seule la vraie mecanique FIFO est exercee par ce test."""
    tenant, locations, variant_ids = _stock_setup()
    internal, _internal_2, supplier, client, _production = locations
    variant_id = variant_ids[0]
    with use_tenant(tenant.id):
        available = Decimal(0)
        move_date = dt.date(2026, 1, 1)
        for is_receive, qty, cost in operations:
            move_date += dt.timedelta(days=1)
            if is_receive or available <= 0:
                move = create_move(
                    tenant=tenant,
                    variant_id=variant_id,
                    qty=qty,
                    uom="pc",
                    location_from=supplier,
                    location_to=internal,
                    date=move_date,
                    move_type=StkMove.TYPE_RECEPTION,
                    unit_cost_mga=cost,
                )
                validate_move(move)
                available += qty
            else:
                consume_qty = min(qty, available)
                move = create_move(
                    tenant=tenant,
                    variant_id=variant_id,
                    qty=consume_qty,
                    uom="pc",
                    location_from=internal,
                    location_to=client,
                    date=move_date,
                    move_type=StkMove.TYPE_LIVRAISON,
                )
                validate_move(move)
                available -= consume_qty

        total_remaining_value = StkValuationLayer.objects.filter(
            tenant=tenant, variant_id=variant_id
        ).aggregate(total=Sum("remaining_value_mga"))["total"] or Decimal(0)
        internal_quant = get_quant(variant_id, internal)
        stock_value = internal_quant.value_mga if internal_quant is not None else Decimal(0)
        assert stock_value == total_remaining_value
