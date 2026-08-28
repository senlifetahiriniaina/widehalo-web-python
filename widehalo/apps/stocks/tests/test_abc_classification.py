"""STK-ABC1/STK-CYCLE1 (classification ABC et comptage cyclique, ST5 du
sous-sequencement `stocks` — cf. plan) : cutoffs Pareto 80/95% cumules,
cadence de comptage cyclique par classe (A=+30j/B=+90j/C=+365j),
`due_cyclic_counts`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkAbcClassification, StkLocation, StkMove
from apps.stocks.services.abc_classification import (
    compute_abc_classification,
    due_cyclic_counts,
)
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.negative_stock import grant_negative_stock_exception
from apps.stocks.services.warehouses import create_location, create_warehouse
from apps.stocks.tests.factories import StkAbcClassificationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def abc_setup():
    tenant = Tenant.objects.create(code="STK-ABC-T", name="Stocks ABC Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        return tenant, internal, client


def _consume(tenant, internal, client, variant_id, qty, unit_cost, date):
    # RG-STK-10 (ST7) : ces tests ne receptionnent volontairement aucun
    # stock avant de consommer (seule la trace `StkMove` compte pour le
    # calcul ABC, la disponibilite reelle du quant est hors de son
    # perimetre) — une exception est donc accordee pour chaque variant
    # avant sa premiere consommation, meme raisonnement/discipline que la
    # resolution appliquee a `test_hypothesis_properties.py` (cf. sa
    # docstring `test_rg_stk_1_...`) : cette regle n'a rien a voir avec ce
    # que ce test verifie (les cutoffs Pareto), seulement avec ce qui est
    # AUTORISE a s'executer en amont.
    authorizer = UserFactory()
    grant_negative_stock_exception(
        tenant=tenant,
        variant_id=variant_id,
        authorized_by=authorizer,
        reason="Exception de test — ABC classification (pas de reception prealable)",
    )
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="pc",
        location_from=internal,
        location_to=client,
        date=date,
        move_type=StkMove.TYPE_LIVRAISON,
        unit_cost_mga=unit_cost,
    )
    return validate_move(move)


def test_compute_abc_classification_hand_verified_cutoffs(abc_setup) -> None:
    """4 produits, valeurs de consommation 500/300/150/50 (total 1000) :
    cumul V1=500 -> 50% (<=80 => A) ; cumul V1+V2=800 -> 80% (<=80 => A,
    borne incluse) ; cumul +V3=950 -> 95% (<=95 => B, borne incluse) ;
    cumul +V4=1000 -> 100% (>95 => C). Verifie a la main contre les
    cutoffs 80/95% cumules documentes dans `services/abc_classification.py`."""
    tenant, internal, client = abc_setup
    with use_tenant(tenant.id):
        # value_mga = qty * unit_cost_mga : 500=50*10, 300=30*10, 150=15*10,
        # 50=5*10 — meme cout unitaire pour isoler la valeur de consommation.
        v1, v2, v3, v4 = (uuid.uuid4() for _ in range(4))
        _consume(tenant, internal, client, v1, Decimal("50"), Decimal("10"), dt.date(2026, 3, 1))
        _consume(tenant, internal, client, v2, Decimal("30"), Decimal("10"), dt.date(2026, 3, 1))
        _consume(tenant, internal, client, v3, Decimal("15"), Decimal("10"), dt.date(2026, 3, 1))
        _consume(tenant, internal, client, v4, Decimal("5"), Decimal("10"), dt.date(2026, 3, 1))

        results = compute_abc_classification(tenant, as_of=dt.date(2026, 3, 15), period_days=90)
        by_variant = {r.variant_id: r for r in results}

        assert len(results) == 4
        assert by_variant[v1].abc_class == StkAbcClassification.CLASS_A
        assert by_variant[v1].consumption_value_mga == Decimal("500.0000")
        assert by_variant[v2].abc_class == StkAbcClassification.CLASS_A
        assert by_variant[v3].abc_class == StkAbcClassification.CLASS_B
        assert by_variant[v4].abc_class == StkAbcClassification.CLASS_C


def test_compute_abc_classification_cadence_next_count_due(abc_setup) -> None:
    tenant, internal, client = abc_setup
    with use_tenant(tenant.id):
        v1, v2, v3 = (uuid.uuid4() for _ in range(3))
        # Un seul produit -> 100% de la valeur cumulee -> classe A (<=80%
        # ne s'applique qu'au premier produit qui, seul, porte 100%... on
        # construit donc 3 produits pour obtenir les 3 classes.
        _consume(tenant, internal, client, v1, Decimal("80"), Decimal("10"), dt.date(2026, 3, 1))
        _consume(tenant, internal, client, v2, Decimal("15"), Decimal("10"), dt.date(2026, 3, 1))
        _consume(tenant, internal, client, v3, Decimal("5"), Decimal("10"), dt.date(2026, 3, 1))

        as_of = dt.date(2026, 3, 15)
        results = compute_abc_classification(tenant, as_of=as_of, period_days=90)
        by_variant = {r.variant_id: r for r in results}

        assert by_variant[v1].abc_class == StkAbcClassification.CLASS_A
        assert by_variant[v1].next_count_due == as_of + dt.timedelta(days=30)
        assert by_variant[v2].abc_class == StkAbcClassification.CLASS_B
        assert by_variant[v2].next_count_due == as_of + dt.timedelta(days=90)
        assert by_variant[v3].abc_class == StkAbcClassification.CLASS_C
        assert by_variant[v3].next_count_due == as_of + dt.timedelta(days=365)


def test_compute_abc_classification_excludes_moves_outside_window(abc_setup) -> None:
    tenant, internal, client = abc_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        _consume(
            tenant, internal, client, variant_id, Decimal("10"), Decimal("10"), dt.date(2025, 1, 1)
        )
        results = compute_abc_classification(tenant, as_of=dt.date(2026, 3, 15), period_days=90)
        assert results == []


def test_compute_abc_classification_excludes_non_consumption_move_types(abc_setup) -> None:
    tenant, internal, client = abc_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        internal_2 = create_location(
            tenant=tenant,
            warehouse=internal.warehouse,
            code="A2",
            name="Rayon A2",
            type=StkLocation.TYPE_INTERNE,
        )
        # RG-STK-10 (ST7) : ce transfert interne->interne part lui aussi
        # d'un emplacement sans stock reel, meme raisonnement/exception que
        # `_consume` ci-dessus.
        grant_negative_stock_exception(
            tenant=tenant,
            variant_id=variant_id,
            authorized_by=UserFactory(),
            reason="Exception de test — ABC classification (transfert sans reception prealable)",
        )
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("10"),
            uom="pc",
            location_from=internal,
            location_to=internal_2,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
            unit_cost_mga=Decimal("10"),
        )
        validate_move(move)
        results = compute_abc_classification(tenant, as_of=dt.date(2026, 3, 15), period_days=90)
        assert results == []


def test_due_cyclic_counts_filters_by_next_count_due(abc_setup) -> None:
    tenant, _internal, _client = abc_setup
    with use_tenant(tenant.id):
        due = StkAbcClassificationFactory(tenant=tenant, next_count_due=dt.date(2026, 3, 1))
        not_due = StkAbcClassificationFactory(tenant=tenant, next_count_due=dt.date(2026, 6, 1))
        results = due_cyclic_counts(tenant, as_of=dt.date(2026, 3, 15))
        result_ids = {r.id for r in results}
        assert due.id in result_ids
        assert not_due.id not in result_ids
