"""EAN-13/GTIN par variante (T1 refonte UX, Sprint 4 / L3, cf.
docs/planning/2026-refonte-ux-sprints.md §5)."""

from __future__ import annotations

import pytest

from apps.catalog.models import ProductTemplate, UnitOfMeasure
from apps.catalog.services.barcodes import (
    EAN13_RESTRICTED_CIRCULATION_PREFIX,
    _ean13_check_digit,
    assign_ean13,
    next_ean13,
)
from apps.catalog.tests.factories import ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_check_digit_matches_a_known_real_ean13() -> None:
    """ "4006381333931" est un EAN-13 reel bien connu (utilise dans la
    documentation GS1) -- verifie l'algorithme contre une valeur externe,
    pas seulement sa propre coherence interne."""
    assert _ean13_check_digit("400638133393") == 1


def test_next_ean13_has_valid_length_prefix_and_checksum() -> None:
    tenant = Tenant.objects.create(code="EAN-1", name="EAN Tenant 1")
    with use_tenant(tenant.id):
        code = next_ean13(tenant)

    assert len(code) == 13
    assert code.isdigit()
    assert code.startswith(EAN13_RESTRICTED_CIRCULATION_PREFIX)
    assert int(code[-1]) == _ean13_check_digit(code[:12])


def test_next_ean13_increments_and_never_collides() -> None:
    tenant = Tenant.objects.create(code="EAN-2", name="EAN Tenant 2")
    with use_tenant(tenant.id):
        codes = {next_ean13(tenant) for _ in range(20)}
    assert len(codes) == 20


def test_assign_ean13_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="EAN-3", name="EAN Tenant 3")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(tenant=tenant, name="Style", base_uom=uom)
        variant = ProductVariantFactory(tenant=tenant, template=template)

        assign_ean13(variant)
        first_code = variant.ean13
        assert first_code

        assign_ean13(variant)
        assert variant.ean13 == first_code
