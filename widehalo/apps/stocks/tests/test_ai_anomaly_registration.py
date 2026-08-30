"""AI3 : adaptateur `apps.stocks.services.ai_anomaly_registration` —
verifie que le check REEL surfacce un `StkQuant` interne effectivement
negatif, avec la severite differenciee selon qu'une exception ST7 active
existe ou non pour le produit concerne."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.anomaly_registry import SEVERITY_HIGH, SEVERITY_MEDIUM, get_anomaly_check
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation
from apps.stocks.services.ai_anomaly_registration import _check_negative_stock
from apps.stocks.tests.factories import (
    StkNegativeStockExceptionFactory,
    StkQuantFactory,
)

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("stocks.negative_stock")
    assert registered is not None
    assert registered.module == "stocks"
    assert registered.function is _check_negative_stock


def test_check_surfaces_negative_internal_quant_without_exception_as_high() -> None:
    tenant = Tenant.objects.create(code="STK-AI3-1", name="Stocks AI3 Tenant 1")
    with use_tenant(tenant.id):
        quant = StkQuantFactory(tenant=tenant, qty=-5)
        assert quant.location.type == StkLocation.TYPE_INTERNE

        candidates = _check_negative_stock(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "stocks.stkquant"
    assert candidate.object_id == str(quant.id)
    assert candidate.severity == SEVERITY_HIGH


def test_check_surfaces_negative_internal_quant_with_exception_as_medium() -> None:
    tenant = Tenant.objects.create(code="STK-AI3-2", name="Stocks AI3 Tenant 2")
    with use_tenant(tenant.id):
        quant = StkQuantFactory(tenant=tenant, qty=-3)
        StkNegativeStockExceptionFactory(tenant=tenant, variant_id=quant.variant_id)

        candidates = _check_negative_stock(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].severity == SEVERITY_MEDIUM


def test_check_ignores_positive_quants_and_virtual_locations() -> None:
    tenant = Tenant.objects.create(code="STK-AI3-3", name="Stocks AI3 Tenant 3")
    with use_tenant(tenant.id):
        StkQuantFactory(tenant=tenant, qty=10)  # positif : jamais une anomalie.

        from apps.stocks.tests.factories import StkLocationFactory

        virtual_location = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_FOURNISSEUR)
        StkQuantFactory(tenant=tenant, qty=-100, location=virtual_location)

        candidates = _check_negative_stock(str(tenant.id))

    assert candidates == []
