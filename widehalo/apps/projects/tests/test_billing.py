"""Tests PJ5 (facturation multi-modes, `services/billing.py`) — cf. plan,
section « Module `projects` », etape PJ5. Reutilise le meme patron de
configuration comptable de test que `apps.sales.tests.test_invoicing.
_setup_accounting` (verifie dans ce fichier reel avant d'ecrire ces tests,
pas devine)."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.projects.models import PrjInvoicingRecord, PrjProject, PrjTask
from apps.projects.services.billing import (
    TimeAndMaterialNotImplementedError,
    bill_by_milestone,
    bill_by_percentage,
    bill_fixed,
    bill_time_and_material,
)
from apps.projects.services.evm import add_budget_line
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task, finish_task, start_task

pytestmark = pytest.mark.django_db


def _setup_accounting(tenant: Tenant) -> None:
    """Cf. `apps.sales.tests.test_invoicing._setup_accounting` — meme
    configuration comptable minimale attendue par
    `accounting.services.public.create_customer_invoice_from_source`."""
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    today = dt.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    AccPeriodFactory(
        tenant=tenant, date_start=today.replace(day=1), date_end=today.replace(day=last_day)
    )
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)


@pytest.fixture
def billing_setup():
    tenant = Tenant.objects.create(code="PRJ-BILL", name="Projects Billing Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="projects-billing@example.com", password="Str0ngPassw0rd!23"
        )
        partner = PartnerFactory(tenant=tenant)
        return tenant, user, partner


def _milestone_task(tenant: Tenant, project: PrjProject, *, amount: Decimal | None) -> PrjTask:
    task = create_task(tenant, project=project, task_type=PrjTask.TYPE_MILESTONE)
    task.budgeted_amount = amount
    task.save(update_fields=["budgeted_amount"])
    return task


# --- bill_by_milestone -------------------------------------------------------------


def test_bill_by_milestone_success(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet jalon", client_partner_id=partner.id)
        task = _milestone_task(tenant, project, amount=Decimal("15000"))
        start_task(task, user)
        finish_task(task, user)

        invoice_id = bill_by_milestone(project, task, user)

        assert invoice_id is not None
        record = PrjInvoicingRecord.objects.get(task=task)
        assert record.mode == PrjInvoicingRecord.MODE_MILESTONE
        assert record.amount == Decimal("15000")
        assert record.invoice_id == invoice_id


def test_bill_by_milestone_refuses_unfinished_task(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet jalon en cours", client_partner_id=partner.id)
        task = _milestone_task(tenant, project, amount=Decimal("1000"))

        with pytest.raises(ValidationError):
            bill_by_milestone(project, task, user)
        assert not PrjInvoicingRecord.objects.filter(task=task).exists()


def test_bill_by_milestone_refuses_non_milestone_task(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet tache", client_partner_id=partner.id)
        task = create_task(tenant, project=project, task_type=PrjTask.TYPE_TASK)
        start_task(task, user)
        finish_task(task, user)

        with pytest.raises(ValidationError):
            bill_by_milestone(project, task, user)


def test_bill_by_milestone_refuses_without_budgeted_amount(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(
            tenant, name="Projet jalon sans montant", client_partner_id=partner.id
        )
        task = _milestone_task(tenant, project, amount=None)
        start_task(task, user)
        finish_task(task, user)

        with pytest.raises(ValidationError):
            bill_by_milestone(project, task, user)


def test_bill_by_milestone_refuses_double_billing(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet jalon double", client_partner_id=partner.id)
        task = _milestone_task(tenant, project, amount=Decimal("500"))
        start_task(task, user)
        finish_task(task, user)
        bill_by_milestone(project, task, user)

        with pytest.raises(ValidationError):
            bill_by_milestone(project, task, user)
        assert PrjInvoicingRecord.objects.filter(task=task).count() == 1


# --- bill_by_percentage -------------------------------------------------------------


def test_bill_by_percentage_bills_incremental_gap(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(
            tenant,
            name="Projet avancement",
            client_partner_id=partner.id,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 31),
        )
        add_budget_line(
            project,
            category="opex",
            label="Ligne",
            planned_amount=Decimal("10000"),
            period=dt.date(2026, 1, 1),
        )
        task = create_task(tenant, project=project, duration_days=1)
        task.percent_complete = 40
        task.save(update_fields=["percent_complete"])

        invoice_id = bill_by_percentage(project, user)
        assert invoice_id is not None
        record = PrjInvoicingRecord.objects.get(
            project=project, mode=PrjInvoicingRecord.MODE_PERCENTAGE
        )
        assert record.amount == Decimal("4000.0000")

        # Meme avancement, rien de nouveau a facturer.
        with pytest.raises(ValidationError):
            bill_by_percentage(project, user)

        # Avancement progresse : facture uniquement l'ECART.
        task.percent_complete = 70
        task.save(update_fields=["percent_complete"])
        invoice_id_2 = bill_by_percentage(project, user)
        assert invoice_id_2 is not None
        total_billed = PrjInvoicingRecord.objects.filter(
            project=project, mode=PrjInvoicingRecord.MODE_PERCENTAGE
        ).count()
        assert total_billed == 2
        second_record = (
            PrjInvoicingRecord.objects.filter(
                project=project, mode=PrjInvoicingRecord.MODE_PERCENTAGE
            )
            .order_by("created_at")
            .last()
        )
        assert second_record.amount == Decimal("3000.0000")


def test_bill_by_percentage_refuses_when_not_calculable(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet sans donnees", client_partner_id=partner.id)

        with pytest.raises(ValidationError):
            bill_by_percentage(project, user)


# --- bill_fixed ----------------------------------------------------------------------


def test_bill_fixed_success_and_refuses_second_billing(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet forfait", client_partner_id=partner.id)

        invoice_id = bill_fixed(project, user, amount=Decimal("25000"))
        assert invoice_id is not None
        record = PrjInvoicingRecord.objects.get(project=project, mode=PrjInvoicingRecord.MODE_FIXED)
        assert record.amount == Decimal("25000")

        with pytest.raises(ValidationError):
            bill_fixed(project, user, amount=Decimal("1000"))
        assert (
            PrjInvoicingRecord.objects.filter(
                project=project, mode=PrjInvoicingRecord.MODE_FIXED
            ).count()
            == 1
        )


def test_bill_fixed_refuses_non_positive_amount(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(
            tenant, name="Projet forfait invalide", client_partner_id=partner.id
        )

        with pytest.raises(ValidationError):
            bill_fixed(project, user, amount=Decimal("0"))


# --- bill_time_and_material (stub honnete) -------------------------------------------


def test_bill_time_and_material_is_an_honest_stub(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet regie", client_partner_id=partner.id)

        with pytest.raises(TimeAndMaterialNotImplementedError):
            bill_time_and_material(project, user, hourly_rate=Decimal("100"))
        assert not PrjInvoicingRecord.objects.filter(project=project).exists()


# --- client_partner_id manquant (commun aux 4 modes) ----------------------------------


def test_all_modes_refuse_without_client_partner(billing_setup) -> None:
    tenant, user, _partner = billing_setup
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        project = create_project(tenant, name="Projet sans client")

        with pytest.raises(ValidationError):
            bill_fixed(project, user, amount=Decimal("100"))
        with pytest.raises(ValidationError):
            bill_by_percentage(project, user)

        task = _milestone_task(tenant, project, amount=Decimal("100"))
        start_task(task, user)
        finish_task(task, user)
        with pytest.raises(ValidationError):
            bill_by_milestone(project, task, user)

        assert not PrjInvoicingRecord.objects.filter(project=project).exists()


# --- gap accounting incomplet (retour None gere gracieusement) ------------------------


def test_bill_fixed_raises_clear_error_without_accounting_config(billing_setup) -> None:
    tenant, user, partner = billing_setup
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet sans compta", client_partner_id=partner.id)

        with pytest.raises(ValidationError):
            bill_fixed(project, user, amount=Decimal("100"))
        assert not PrjInvoicingRecord.objects.filter(project=project).exists()
