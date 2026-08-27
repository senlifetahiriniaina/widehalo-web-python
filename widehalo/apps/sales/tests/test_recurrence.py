"""S5 : planification periodique (`SalesRecurrence`, RG-SAL-6). Le test le
plus important de ce module est `test_generate_due_order_never_confirms_the_new_order`
— la regle explicite du CDC ("La generation n'est jamais automatiquement
confirmee") n'a de valeur que si un test echoue le jour ou quelqu'un
cablerait par erreur `confirm_order` a la suite de la generation."""

from __future__ import annotations

import datetime as dt

import pytest
from freezegun import freeze_time

from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder, SalesRecurrence
from apps.sales.services.orders import add_order_line, create_order
from apps.sales.services.recurrence import (
    create_recurrence,
    generate_due_order,
    run_due_recurrences,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def recurrence_setup():
    tenant = Tenant.objects.create(code="SALES-REC", name="Sales Recurrence Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="sales-rec@example.com", password="Str0ngPassw0rd!23")
        partner = PartnerFactory(tenant=tenant)
        template = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(template, description="Abonnement mensuel", qty=1, unit_price=100000)
        return tenant, user, template


def test_generate_due_order_never_confirms_the_new_order(recurrence_setup) -> None:
    """RG-SAL-6, controle explicite : la commande generee est TOUJOURS en
    `draft`, jamais `confirmed` — c'est le coeur de la regle."""
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        recurrence = create_recurrence(
            tenant=tenant,
            name="Facturation mensuelle",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today(),
            template_order=template,
        )
        new_order = generate_due_order(recurrence, user)

        assert new_order is not None
        assert new_order.state == SalesOrder.STATE_DRAFT
        assert new_order.state != SalesOrder.STATE_CONFIRMED
        assert new_order.is_recurring is True
        assert new_order.recurrence_id == recurrence.id
        assert new_order.partner_id == template.partner_id
        assert new_order.lines.count() == template.lines.count()


def test_generate_due_order_copies_template_lines(recurrence_setup) -> None:
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        recurrence = create_recurrence(
            tenant=tenant,
            name="Copie de lignes",
            interval=SalesRecurrence.INTERVAL_WEEKLY,
            start_date=dt.date.today(),
            template_order=template,
        )
        new_order = generate_due_order(recurrence, user)
        assert new_order is not None
        new_line = new_order.lines.get()
        template_line = template.lines.get()
        assert new_line.description == template_line.description
        assert new_line.qty == template_line.qty
        assert new_line.unit_price == template_line.unit_price
        assert new_order.amount_total_mga == template.amount_total_mga


def test_generate_due_order_returns_none_when_inactive(recurrence_setup) -> None:
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        recurrence = create_recurrence(
            tenant=tenant,
            name="Recurrence inactive",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today(),
            template_order=template,
        )
        recurrence.is_active = False
        recurrence.save(update_fields=["is_active"])

        assert generate_due_order(recurrence, user) is None
        assert SalesOrder.objects.filter(recurrence_id=recurrence.id).count() == 0


def test_generate_due_order_returns_none_when_not_yet_due(recurrence_setup) -> None:
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        recurrence = create_recurrence(
            tenant=tenant,
            name="Pas encore a echeance",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today() + dt.timedelta(days=30),
            template_order=template,
        )
        assert generate_due_order(recurrence, user) is None


def test_generate_due_order_returns_none_past_end_date(recurrence_setup) -> None:
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        recurrence = create_recurrence(
            tenant=tenant,
            name="Recurrence echue",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today() - dt.timedelta(days=60),
            template_order=template,
            end_date=dt.date.today() - dt.timedelta(days=1),
        )
        assert generate_due_order(recurrence, user) is None


@pytest.mark.parametrize(
    "interval,expected",
    [
        (SalesRecurrence.INTERVAL_WEEKLY, dt.date(2026, 1, 8)),
        (SalesRecurrence.INTERVAL_MONTHLY, dt.date(2026, 2, 1)),
        (SalesRecurrence.INTERVAL_QUARTERLY, dt.date(2026, 4, 1)),
        (SalesRecurrence.INTERVAL_YEARLY, dt.date(2027, 1, 1)),
    ],
)
def test_next_run_advances_correctly_per_interval(recurrence_setup, interval, expected) -> None:
    tenant, user, template = recurrence_setup
    with freeze_time("2026-01-01"), use_tenant(tenant.id):
        recurrence = create_recurrence(
            tenant=tenant,
            name=f"Avance {interval}",
            interval=interval,
            start_date=dt.date(2026, 1, 1),
            template_order=template,
        )
        assert recurrence.next_run == dt.date(2026, 1, 1)
        generate_due_order(recurrence, user)
        recurrence.refresh_from_db()
        assert recurrence.next_run == expected


def test_generate_due_order_dispatches_a_notification_to_the_salesperson(
    recurrence_setup,
) -> None:
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        salesperson = User.objects.create_user(
            email="sales-rec-commercial@example.com", password="Str0ngPassw0rd!23"
        )
        template.salesperson = salesperson
        template.save(update_fields=["salesperson"])

        recurrence = create_recurrence(
            tenant=tenant,
            name="Notifie le commercial",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today(),
            template_order=template,
        )
        new_order = generate_due_order(recurrence, user)

        assert new_order is not None
        notification = Notification.objects.get(
            user=salesperson, notification_type="sales.recurring_order_generated"
        )
        assert notification.payload["order_id"] == str(new_order.id)


def test_run_due_recurrences_processes_due_and_skips_not_yet_due(recurrence_setup) -> None:
    tenant, user, template = recurrence_setup
    with use_tenant(tenant.id):
        due = create_recurrence(
            tenant=tenant,
            name="A echeance",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today(),
            template_order=template,
        )
        not_due = create_recurrence(
            tenant=tenant,
            name="Pas encore",
            interval=SalesRecurrence.INTERVAL_MONTHLY,
            start_date=dt.date.today() + dt.timedelta(days=15),
            template_order=template,
        )

        generated = run_due_recurrences(tenant, user)

        assert len(generated) == 1
        assert generated[0].recurrence_id == due.id
        not_due.refresh_from_db()
        assert not_due.next_run == dt.date.today() + dt.timedelta(days=15)
