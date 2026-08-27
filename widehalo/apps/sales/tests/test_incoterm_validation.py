"""RG-SAL-9 (§5.5.3, S6) : "Champ [incoterm] obligatoire sur les commandes
a l'export" — `SalesOrder.is_export` (saisi par l'utilisateur) rend
`incoterm` obligatoire, verifie a `confirm_order` (cf.
`apps.sales.services.orders.ensure_incoterm_for_export`)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder
from apps.sales.services.orders import confirm_order, create_order, ensure_incoterm_for_export

pytestmark = pytest.mark.django_db


@pytest.fixture
def incoterm_setup():
    tenant = Tenant.objects.create(code="SALES-INCOTERM", name="Sales Incoterm Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="sales-incoterm@example.com", password="Str0ngPassw0rd!23"
        )
        partner = PartnerFactory(tenant=tenant)
        return tenant, user, partner


def test_export_order_without_incoterm_cannot_be_confirmed(incoterm_setup) -> None:
    tenant, user, partner = incoterm_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant, partner_id=partner.id, date=dt.date.today(), is_export=True
        )
        assert order.incoterm == ""
        with pytest.raises(ValidationError):
            confirm_order(order, user)
        order.refresh_from_db()
        assert order.state == SalesOrder.STATE_DRAFT


def test_export_order_with_incoterm_can_be_confirmed(incoterm_setup) -> None:
    tenant, user, partner = incoterm_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant,
            partner_id=partner.id,
            date=dt.date.today(),
            is_export=True,
            incoterm=SalesOrder.INCOTERM_FOB,
        )
        confirm_order(order, user)
        order.refresh_from_db()
        assert order.state == SalesOrder.STATE_CONFIRMED


def test_non_export_order_never_requires_incoterm(incoterm_setup) -> None:
    tenant, user, partner = incoterm_setup
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        assert order.is_export is False
        confirm_order(order, user)
        order.refresh_from_db()
        assert order.state == SalesOrder.STATE_CONFIRMED


def test_ensure_incoterm_for_export_helper_directly(incoterm_setup) -> None:
    tenant, _user, partner = incoterm_setup
    with use_tenant(tenant.id):
        order = create_order(
            tenant=tenant, partner_id=partner.id, date=dt.date.today(), is_export=True
        )
        with pytest.raises(ValidationError):
            ensure_incoterm_for_export(order)

        order.incoterm = SalesOrder.INCOTERM_EXW
        ensure_incoterm_for_export(order)  # ne leve plus rien
