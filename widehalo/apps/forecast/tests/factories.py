"""Factories factory_boy pour les modèles du module `forecast`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import factory
from apps.forecast.models import ForExceptionalPoint, ForHoliday, ForPublication, ForSeriesForecast
from django.utils import timezone


class ForHolidayFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ForHoliday

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    date = factory.Sequence(lambda n: dt.date(2026, 1, 1) + dt.timedelta(days=n))
    name = factory.Sequence(lambda n: f"Jour férié {n}")


class ForExceptionalPointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ForExceptionalPoint

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    dimension_type = ForExceptionalPoint.DIMENSION_CANAL
    dimension_value = "pos"
    period = dt.date(2026, 6, 1)
    reason = "Rupture d'approvisionnement"


class ForSeriesForecastFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ForSeriesForecast

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    dimension_type = ForSeriesForecast.DIMENSION_CANAL
    dimension_value = "pos"
    period = factory.Sequence(lambda n: dt.date(2026, 1, 1) + dt.timedelta(days=32 * n))
    reference_naive_value = Decimal("1000")
    selected_model = ForSeriesForecast.MODEL_MOYENNE_MOBILE
    selected_model_score = Decimal("5.0000")
    test_window_start = dt.date(2025, 7, 1)
    test_window_end = dt.date(2025, 12, 1)
    statistical_value = Decimal("1000")
    computed_at = factory.LazyFunction(timezone.now)


class ForPublicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ForPublication

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    version = factory.Sequence(lambda n: n + 1)
    published_at = factory.LazyFunction(timezone.now)
    period_start = dt.date(2026, 1, 1)
    period_end = dt.date(2026, 6, 1)
    snapshot = factory.LazyFunction(list)
