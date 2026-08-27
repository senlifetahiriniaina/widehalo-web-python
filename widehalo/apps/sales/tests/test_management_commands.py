"""S5 : commande de management `run_sales_recurrences` (declenchement ops
de RG-SAL-6, cf. `apps.sales.services.recurrence` pour la justification du
choix retenu — pas d'enqueue Django-Q2, appel synchrone par tenant)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder, SalesRecurrence
from apps.sales.services.orders import add_order_line, create_order
from apps.sales.services.recurrence import create_recurrence

pytestmark = pytest.mark.django_db


def test_run_sales_recurrences_command_generates_due_orders() -> None:
    tenant = Tenant.objects.create(code="SALES-CMD", name="Sales Command Tenant")
    with use_tenant(tenant.id):
        User.objects.create_superuser(
            email="sales-cmd-admin@example.com", password="Str0ngPassw0rd!23"
        )
        partner = PartnerFactory(tenant=tenant)
        template = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(template, description="Abonnement", qty=1, unit_price=50000)
        recurrence = create_recurrence(
            tenant=tenant,
            name="Recurrence ops",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today(),
            template_order=template,
        )

    call_command("run_sales_recurrences")

    with use_tenant(tenant.id):
        generated = SalesOrder.objects.filter(recurrence_id=recurrence.id).exclude(pk=template.pk)
        assert generated.count() == 1
        assert generated.get().state == SalesOrder.STATE_DRAFT

        recurrence.refresh_from_db()
        assert recurrence.next_run > dt.date.today()


def test_run_sales_recurrences_command_skips_tenant_without_superuser() -> None:
    tenant = Tenant.objects.create(code="SALES-CMD-NOSU", name="Sales Command No Superuser")
    with use_tenant(tenant.id):
        partner = PartnerFactory(tenant=tenant)
        template = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(template, description="Abonnement", qty=1, unit_price=50000)
        create_recurrence(
            tenant=tenant,
            name="Recurrence sans admin",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today(),
            template_order=template,
        )

    # Ne doit pas lever malgre l'absence de superutilisateur pour ce tenant.
    call_command("run_sales_recurrences")

    with use_tenant(tenant.id):
        assert SalesOrder.objects.filter(tenant=tenant).count() == 1
