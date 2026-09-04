"""Ajustement humain (`services/adjustments.py`) — cahier Phase 2 §13.2,
FOR-6/FOR-7."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.forecast.services.adjustments import (
    apply_adjustment,
    measure_adjustment_contribution,
    revert_adjustment,
)
from apps.forecast.tests.factories import ForSeriesForecastFactory
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def adjustment_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-ADJ", name="Forecast Adjustment Tenant")


def test_apply_adjustment_never_overwrites_statistical_value(adjustment_tenant: Tenant) -> None:
    with use_tenant(adjustment_tenant.id):
        forecast = ForSeriesForecastFactory(
            tenant=adjustment_tenant, statistical_value=Decimal("1000")
        )
        user = UserFactory()

        apply_adjustment(forecast, new_value=Decimal("1200"), reason="Campagne connue", user=user)

        forecast.refresh_from_db()
        assert forecast.statistical_value == Decimal("1000")
        assert forecast.adjusted_value == Decimal("1200")
        assert forecast.final_value == Decimal("1200")
        assert len(forecast.adjustment_history) == 1
        entry = forecast.adjustment_history[0]
        assert entry["reason"] == "Campagne connue"
        assert entry["before"] == "1000"
        assert entry["after"] == "1200"
        assert entry["author_id"] == str(user.id)


def test_apply_adjustment_requires_a_reason(adjustment_tenant: Tenant) -> None:
    with use_tenant(adjustment_tenant.id):
        forecast = ForSeriesForecastFactory(tenant=adjustment_tenant)
        user = UserFactory()

        with pytest.raises(ValidationError):
            apply_adjustment(forecast, new_value=Decimal("1200"), reason="   ", user=user)


def test_revert_adjustment_returns_to_statistical_value_and_is_traced(
    adjustment_tenant: Tenant,
) -> None:
    with use_tenant(adjustment_tenant.id):
        forecast = ForSeriesForecastFactory(
            tenant=adjustment_tenant, statistical_value=Decimal("1000")
        )
        user = UserFactory()
        apply_adjustment(forecast, new_value=Decimal("1200"), reason="Test", user=user)

        revert_adjustment(forecast, user=user, reason="Erreur de saisie")

        forecast.refresh_from_db()
        assert forecast.adjusted_value == Decimal("1000")
        assert len(forecast.adjustment_history) == 2


def test_measure_adjustment_contribution_computes_both_errors(adjustment_tenant: Tenant) -> None:
    with use_tenant(adjustment_tenant.id):
        forecast = ForSeriesForecastFactory(
            tenant=adjustment_tenant,
            statistical_value=Decimal("900"),
            adjusted_value=Decimal("950"),
        )

        measure_adjustment_contribution(forecast, actual_value=Decimal("1000"))

        forecast.refresh_from_db()
        assert forecast.statistical_error_pct == Decimal("10.00")
        assert forecast.adjustment_error_pct == Decimal("5.00")
