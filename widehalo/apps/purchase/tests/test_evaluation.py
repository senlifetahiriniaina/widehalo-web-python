"""Tests PU7 (RG-PUR-8, §5.6.2, cf. plan) : `count_disputes_for_supplier`
et `apply_score_to_priority` (mutualisation MRP-QQCD1 — le calcul de
`weighted_score` lui-meme est teste cote `mrp`, cf.
`apps/mrp/tests/test_public.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import ProductSupplierInfo, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.services.public import record_supplier_evaluation
from apps.purchase.services.evaluation import apply_score_to_priority, count_disputes_for_supplier
from apps.purchase.tests.factories import PurCriFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def evaluation_setup():
    tenant = Tenant.objects.create(code="PUR-EVAL", name="Purchase Evaluation Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Tissu coton",
            base_uom=uom,
            reference="TPL-PUR-EVAL-0001",
            base_price_mga=Decimal("5000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-EVAL-0001"
        )
        return tenant, variant


def test_count_disputes_for_supplier_counts_within_window(evaluation_setup) -> None:
    tenant, _variant = evaluation_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        other_partner_id = uuid.uuid4()
        PurCriFactory(tenant=tenant, partner_id=partner_id, date=dt.date(2026, 1, 5))
        PurCriFactory(tenant=tenant, partner_id=partner_id, date=dt.date(2026, 2, 20))
        # Hors fenetre : avant period_start.
        PurCriFactory(tenant=tenant, partner_id=partner_id, date=dt.date(2025, 12, 1))
        # Autre fournisseur : jamais compte.
        PurCriFactory(tenant=tenant, partner_id=other_partner_id, date=dt.date(2026, 1, 15))

        count = count_disputes_for_supplier(
            partner_id, period_start=dt.date(2026, 1, 1), period_end=dt.date(2026, 3, 31)
        )
        assert count == 2


def test_count_disputes_for_supplier_returns_zero_without_incident(evaluation_setup) -> None:
    tenant, _variant = evaluation_setup
    with use_tenant(tenant.id):
        count = count_disputes_for_supplier(
            uuid.uuid4(), period_start=dt.date(2026, 1, 1), period_end=dt.date(2026, 3, 31)
        )
        assert count == 0


def test_apply_score_to_priority_returns_zero_without_evaluation(evaluation_setup) -> None:
    tenant, variant = evaluation_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        ProductSupplierInfo.objects.create(tenant=tenant, variant=variant, partner_id=partner_id)
        assert apply_score_to_priority(partner_id) == 0


def test_apply_score_to_priority_updates_matching_rows_with_hand_checked_example(
    evaluation_setup,
) -> None:
    """Exemple verifie a la main (cf. docstring `services/evaluation.py`) :
    5 notes/5, poids par defaut (18/30/27/13/12, somme=100) :
    weighted = (4*18 + 4*30 + 4*27 + 4*13 + 4*12) / 5
             = (72 + 120 + 108 + 52 + 48) / 5 = 400 / 5 = 80.00
    priority = max(1, 100 - int(80)) = 20."""
    tenant, variant = evaluation_setup
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        info = ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=partner_id, priority=10
        )
        other_partner_info = ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=uuid.uuid4(), priority=10
        )

        evaluation_id = record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 3, 31),
            score_quantity=Decimal("4"),
            score_quality=Decimal("4"),
            score_cost=Decimal("4"),
            score_delay=Decimal("4"),
            score_conformity=Decimal("4"),
        )
        assert evaluation_id is not None

        updated = apply_score_to_priority(partner_id)
        assert updated == 1

        info.refresh_from_db()
        other_partner_info.refresh_from_db()
        assert info.priority == 20
        assert other_partner_info.priority == 10


def test_apply_score_to_priority_restricts_to_given_variant_ids(evaluation_setup) -> None:
    tenant, variant = evaluation_setup
    with use_tenant(tenant.id):
        other_uom = UnitOfMeasure.objects.filter(tenant=tenant).first()
        other_template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Tissu polyester",
            base_uom=other_uom,
            reference="TPL-PUR-EVAL-0002",
            base_price_mga=Decimal("3000"),
        )
        other_variant = ProductVariant.objects.create(
            tenant=tenant, template=other_template, reference="VAR-PUR-EVAL-0002"
        )
        partner_id = uuid.uuid4()
        info_targeted = ProductSupplierInfo.objects.create(
            tenant=tenant, variant=variant, partner_id=partner_id, priority=10
        )
        info_untouched = ProductSupplierInfo.objects.create(
            tenant=tenant, variant=other_variant, partner_id=partner_id, priority=10
        )

        record_supplier_evaluation(
            tenant=tenant,
            partner_id=partner_id,
            date=dt.date(2026, 3, 31),
            score_quantity=Decimal("5"),
            score_quality=Decimal("5"),
            score_cost=Decimal("5"),
            score_delay=Decimal("5"),
            score_conformity=Decimal("5"),
        )

        updated = apply_score_to_priority(partner_id, variant_ids=[variant.id])
        assert updated == 1

        info_targeted.refresh_from_db()
        info_untouched.refresh_from_db()
        assert info_targeted.priority == 1
        assert info_untouched.priority == 10
