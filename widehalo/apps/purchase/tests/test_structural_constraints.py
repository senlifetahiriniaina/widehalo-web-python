"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `purchase` — comble le trou laisse par la premiere passe
de verification des 14 couches (fermee avant que ce module n'existe). Meme
discipline que `apps.mrp.tests.test_structural_constraints` : `on_delete`
(PROTECT/CASCADE/SET_NULL) de chaque FK non triviale du module, plus les
`UniqueConstraint` posees.

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import pytest
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurOrderLine, PurRequisitionLine, PurRfqLine
from apps.purchase.tests.factories import (
    PurCraFactory,
    PurOrderFactory,
    PurOrderLineFactory,
    PurRequisitionFactory,
    PurRequisitionLineFactory,
    PurRfqFactory,
    PurRfqLineFactory,
    PurRfqSupplierFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_requester_cannot_be_deleted_while_referenced_by_a_requisition() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        requisition = PurRequisitionFactory(tenant=tenant)
        requester = requisition.requester

        with pytest.raises(ProtectedError):
            requester.delete()


def test_buyer_cannot_be_deleted_while_referenced_by_a_cra() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        cra = PurCraFactory(tenant=tenant)
        buyer = cra.buyer

        with pytest.raises(ProtectedError):
            buyer.delete()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_deleting_a_requisition_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = PurRequisitionLineFactory(tenant=tenant)
        requisition = line.requisition
        line_id = line.id

        requisition.delete()

        assert not PurRequisitionLine.objects.filter(pk=line_id).exists()


def test_deleting_an_order_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = PurOrderLineFactory(tenant=tenant)
        order = line.order
        line_id = line.id

        order.delete()

        assert not PurOrderLine.objects.filter(pk=line_id).exists()


def test_deleting_an_rfq_cascades_to_its_lines_and_suppliers() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = PurRfqLineFactory(tenant=tenant)
        supplier = PurRfqSupplierFactory(tenant=tenant, rfq=line.rfq)
        rfq = line.rfq
        line_id = line.id
        supplier_id = supplier.id

        rfq.delete()

        assert not PurRfqLine.objects.filter(pk=line_id).exists()
        from apps.purchase.models import PurRfqSupplier

        assert not PurRfqSupplier.objects.filter(pk=supplier_id).exists()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_requisition_nullifies_the_order_source() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        requisition = PurRequisitionFactory(tenant=tenant)
        order = PurOrderFactory(tenant=tenant, requisition=requisition)

        requisition.delete()
        order.refresh_from_db()

        assert order.requisition_id is None


def test_deleting_an_rfq_nullifies_the_order_source() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        rfq = PurRfqFactory(tenant=tenant)
        order = PurOrderFactory(tenant=tenant, rfq=rfq)

        rfq.delete()
        order.refresh_from_db()

        assert order.rfq_id is None


def test_deleting_an_order_nullifies_the_cra_entry() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        order = PurOrderFactory(tenant=tenant)
        cra = PurCraFactory(tenant=tenant, order=order)

        order.delete()
        cra.refresh_from_db()

        assert cra.order_id is None


# --------------------------------------------------------------------------
# UniqueConstraint
# --------------------------------------------------------------------------


def test_rfq_supplier_unique_per_rfq_and_partner() -> None:
    """`PurRfqSupplier.Meta.constraints` : `uniq_pur_rfq_supplier_rfq_partner`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        rfq = PurRfqFactory(tenant=tenant)
        partner_id = PurRfqSupplierFactory(tenant=tenant, rfq=rfq).partner_id

        with pytest.raises(IntegrityError), transaction.atomic():
            PurRfqSupplierFactory(tenant=tenant, rfq=rfq, partner_id=partner_id)
