"""Contrat public de `analytics` (`services/public.py`) — surface consommée
par le futur module BI (Phase 2 §13.1)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.public import (
    get_metric_definition,
    get_partner_payment_behavior,
    get_sales_value_series,
    get_warehouse_state,
    list_published_metrics,
)
from apps.analytics.tests.factories import (
    AnDimTempsFactory,
    AnDimTiersFactory,
    AnFactEncaissementFactory,
    AnFactVenteFactory,
    AnMetricDefinitionFactory,
    AnWarehouseStateFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_tenant() -> Tenant:
    return Tenant.objects.create(code="AN-PUB", name="Analytics Public Tenant")


def test_get_warehouse_state_none_when_never_refreshed(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        assert get_warehouse_state(public_tenant) is None


def test_get_warehouse_state_reflects_lock(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        AnWarehouseStateFactory(tenant=public_tenant, is_locked=True)
        state = get_warehouse_state(public_tenant)
    assert state == {"is_locked": True, "last_successful_refresh_at": None}


def test_list_published_metrics_returns_primitives(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        AnMetricDefinitionFactory(
            tenant=public_tenant,
            code="ca.mensuel",
            libelle="CA mensuel",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        user = UserFactory()
        grant_role(user, "direction")
        results = list_published_metrics(public_tenant, user)
    assert results == [
        {
            "code": "ca.mensuel",
            "libelle": "CA mensuel",
            "unite": "",
            "module_source": "sales",
            "axes_autorises": [],
            "maille_minimale": "",
        }
    ]


def test_get_metric_definition_returns_none_when_absent(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        assert get_metric_definition(public_tenant, "does.not.exist") is None


def test_get_sales_value_series_merges_channels_without_double_counting(
    public_tenant: Tenant,
) -> None:
    """FOR-8 (module `forecast`) : `vente_directe` n'agrège que
    `AnFactVente`, `pos` n'agrège que `AnFactTicketPos`."""
    with use_tenant(public_tenant.id):
        dim_temps = AnDimTempsFactory(tenant=public_tenant, date=dt.date(2026, 3, 10))
        AnFactVenteFactory(
            tenant=public_tenant, dim_temps=dim_temps, montant_ht_mga=Decimal("1000")
        )

        series = get_sales_value_series(
            public_tenant, dimension_type="canal", dimension_value="vente_directe"
        )

    assert series == [{"period": dt.date(2026, 3, 1), "value": Decimal("1000")}]


def test_get_sales_value_series_fills_gaps_with_zero(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        jan = AnDimTempsFactory(tenant=public_tenant, date=dt.date(2026, 1, 10))
        march = AnDimTempsFactory(tenant=public_tenant, date=dt.date(2026, 3, 10))
        AnFactVenteFactory(tenant=public_tenant, dim_temps=jan, montant_ht_mga=Decimal("100"))
        AnFactVenteFactory(tenant=public_tenant, dim_temps=march, montant_ht_mga=Decimal("300"))

        series = get_sales_value_series(
            public_tenant, dimension_type="canal", dimension_value="vente_directe"
        )

    assert [row["period"] for row in series] == [
        dt.date(2026, 1, 1),
        dt.date(2026, 2, 1),
        dt.date(2026, 3, 1),
    ]
    assert series[1]["value"] == Decimal(0)


def test_get_sales_value_series_returns_empty_for_unknown_dimension(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        assert (
            get_sales_value_series(public_tenant, dimension_type="bogus", dimension_value="x") == []
        )


def test_get_partner_payment_behavior_computes_average_delay(public_tenant: Tenant) -> None:
    """FOR-9 (module `forecast`) : délai observé par client, pas un délai
    théorique unique — un client sans encaissement observé est absent."""
    with use_tenant(public_tenant.id):
        tiers = AnDimTiersFactory(tenant=public_tenant, nom="Client Fidèle")
        vente_temps = AnDimTempsFactory(tenant=public_tenant, date=dt.date(2026, 1, 1))
        encaissement_temps = AnDimTempsFactory(tenant=public_tenant, date=dt.date(2026, 1, 31))
        AnFactVenteFactory(tenant=public_tenant, dim_tiers=tiers, dim_temps=vente_temps)
        AnFactEncaissementFactory(
            tenant=public_tenant, dim_tiers=tiers, dim_temps=encaissement_temps
        )

        # Un second client sans encaissement observé : absent du résultat.
        other_tiers = AnDimTiersFactory(tenant=public_tenant, nom="Client Sans Paiement")
        AnFactVenteFactory(tenant=public_tenant, dim_tiers=other_tiers)

        results = get_partner_payment_behavior(public_tenant)

    assert len(results) == 1
    assert results[0]["nom"] == "Client Fidèle"
    assert results[0]["avg_delay_days"] == 30
