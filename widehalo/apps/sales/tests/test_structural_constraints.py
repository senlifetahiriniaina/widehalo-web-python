"""T2 (couches 4-5 du CDC, §8) : contraintes structurelles/d'interdependance
au niveau base pour `sales` — comble le trou laisse par la premiere passe de
verification des 14 couches (fermee avant que ce module n'existe). Comme
pour `mrp`, comportement `on_delete` (PROTECT/CASCADE/SET_NULL) de chaque FK
du module, plus la `UniqueConstraint` de `SalesForecast`.

RLS (isolation tenant) est hors-perimetre (couverte ailleurs)."""

from __future__ import annotations

import uuid

import pytest
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError

from apps.core.models.user import User
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.sales.models import SalesOrderLine, SalesQuotationLine
from apps.sales.tests.factories import (
    SalesForecastFactory,
    SalesOrderFactory,
    SalesOrderLineFactory,
    SalesQuotationFactory,
    SalesQuotationLineFactory,
    SalesRecurrenceFactory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# on_delete=PROTECT
# --------------------------------------------------------------------------


def test_template_order_cannot_be_deleted_while_referenced_by_a_recurrence() -> None:
    """`SalesRecurrence.template_order` est PROTECT : un gabarit encore
    utilise par une recurrence ne peut pas etre supprime silencieusement."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        recurrence = SalesRecurrenceFactory(tenant=tenant)
        template_order = recurrence.template_order

        with pytest.raises(ProtectedError):
            template_order.delete()


# --------------------------------------------------------------------------
# on_delete=CASCADE
# --------------------------------------------------------------------------


def test_deleting_a_quotation_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = SalesQuotationLineFactory(tenant=tenant)
        quotation = line.quotation
        line_id = line.id

        quotation.delete()

        assert not SalesQuotationLine.objects.filter(pk=line_id).exists()


def test_deleting_an_order_cascades_to_its_lines() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        line = SalesOrderLineFactory(tenant=tenant)
        order = line.order
        line_id = line.id

        order.delete()

        assert not SalesOrderLine.objects.filter(pk=line_id).exists()


# --------------------------------------------------------------------------
# on_delete=SET_NULL
# --------------------------------------------------------------------------


def test_deleting_a_salesperson_nullifies_the_quotation() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        salesperson = User.objects.create_user(
            email="sp-q@example.com", password="Str0ngPassw0rd!23"
        )
        quotation = SalesQuotationFactory(tenant=tenant, salesperson=salesperson)

        salesperson.delete()
        quotation.refresh_from_db()

        assert quotation.salesperson_id is None


def test_deleting_a_salesperson_nullifies_the_order() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        salesperson = User.objects.create_user(
            email="sp-o@example.com", password="Str0ngPassw0rd!23"
        )
        order = SalesOrderFactory(tenant=tenant, salesperson=salesperson)

        salesperson.delete()
        order.refresh_from_db()

        assert order.salesperson_id is None


def test_deleting_a_quotation_nullifies_the_order_source() -> None:
    """`SalesOrder.quotation` est SET_NULL : la commande generee survit a la
    suppression du devis d'origine, seul le lien de tracabilite est perdu."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        quotation = SalesQuotationFactory(tenant=tenant)
        order = SalesOrderFactory(tenant=tenant, quotation=quotation)

        quotation.delete()
        order.refresh_from_db()

        assert order.quotation_id is None


# --------------------------------------------------------------------------
# UniqueConstraint
# --------------------------------------------------------------------------


def test_sales_forecast_unique_per_tenant_period_variant_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        period = "2026-03"
        variant_id = uuid.uuid4()
        partner_id = uuid.uuid4()
        SalesForecastFactory(
            tenant=tenant, period=period, variant_id=variant_id, partner_id=partner_id
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            SalesForecastFactory(
                tenant=tenant, period=period, variant_id=variant_id, partner_id=partner_id
            )
