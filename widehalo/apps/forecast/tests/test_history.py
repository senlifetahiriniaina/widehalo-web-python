"""Historique de série (`services/history.py`) — cahier Phase 2 §13.2,
FOR-4 : points exceptionnels exclus de l'apprentissage sans disparaître
de l'historique affiché."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.analytics.tests.factories import AnDimTempsFactory, AnFactVenteFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.forecast.services.history import load_series_history
from apps.forecast.tests.factories import ForExceptionalPointFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def history_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-HIST", name="Forecast History Tenant")


def test_exceptional_point_excluded_from_training_but_present_in_full_history(
    history_tenant: Tenant,
) -> None:
    with use_tenant(history_tenant.id):
        # Deux mois DISTINCTS (`AnDimTempsFactory` par defaut incremente
        # par jour, insuffisant pour separer deux periodes mensuelles).
        january = AnDimTempsFactory(tenant=history_tenant, date=dt.date(2026, 1, 15))
        february = AnDimTempsFactory(tenant=history_tenant, date=dt.date(2026, 2, 15))
        AnFactVenteFactory(tenant=history_tenant, dim_temps=january, montant_ht_mga=Decimal("1000"))
        fact = AnFactVenteFactory(
            tenant=history_tenant, dim_temps=february, montant_ht_mga=Decimal("5000")
        )
        exceptional_period = fact.dim_temps.date.replace(day=1)
        ForExceptionalPointFactory(
            tenant=history_tenant,
            dimension_type="canal",
            dimension_value="vente_directe",
            period=exceptional_period,
            reason="Promotion isolée",
        )

        history = load_series_history(
            history_tenant, dimension_type="canal", dimension_value="vente_directe"
        )

        assert exceptional_period in history.full_periods
        assert exceptional_period not in history.training_periods
        assert len(history.full_periods) == len(history.full_values)
        assert len(history.training_periods) == len(history.full_periods) - 1
