"""INT2 : `services.ai_anomaly_registration` — anomalie d'information
fournisseur sans prix renseigne (`ProductSupplierInfo.price_mga`)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.services.ai_anomaly_registration import (
    _check_supplier_info_missing_price,
)
from apps.catalog.tests.factories import ProductSupplierInfoFactory
from apps.core.services.anomaly_registry import SEVERITY_MEDIUM, get_anomaly_check
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_check_is_registered_in_the_shared_registry() -> None:
    registered = get_anomaly_check("catalog.supplier_info_missing_price")
    assert registered is not None
    assert registered.module == "catalog"
    assert registered.function is _check_supplier_info_missing_price


def test_check_returns_empty_list_for_tenant_without_data() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        candidates = _check_supplier_info_missing_price(str(tenant.id))

    assert candidates == []


def test_check_ignores_a_supplier_info_with_a_price() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        ProductSupplierInfoFactory(tenant=tenant, price_mga=Decimal("500.0000"))

        candidates = _check_supplier_info_missing_price(str(tenant.id))

    assert candidates == []


def test_check_flags_a_supplier_info_without_a_price() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        info = ProductSupplierInfoFactory(tenant=tenant, price_mga=Decimal("0.0000"))

        candidates = _check_supplier_info_missing_price(str(tenant.id))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.content_type_label == "catalog.productsupplierinfo"
    assert candidate.object_id == str(info.id)
    assert candidate.severity == SEVERITY_MEDIUM
    assert info.variant.reference in candidate.description
