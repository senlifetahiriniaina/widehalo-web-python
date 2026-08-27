"""T10 : la commande `seed_accounting` cree un jeu de demonstration
coherent et est idempotente (rejouee deux fois, ne duplique pas les 3
factures de demonstration)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_seed_accounting_creates_coherent_demo_dataset() -> None:
    call_command("seed_accounting", tenant_code="TEST-SEED-ACC")
    tenant = Tenant.objects.get(code="TEST-SEED-ACC")

    with use_tenant(tenant.id):
        assert AccAccount.objects.filter(tenant=tenant).count() > 0
        assert AccFiscalYear.objects.filter(tenant=tenant, code="FY2026").exists()
        assert AccPeriod.objects.filter(tenant=tenant, code="2026-01").exists()
        assert AccJournal.objects.filter(tenant=tenant, code="VTE").exists()

        invoices = AccMove.objects.filter(tenant=tenant, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        assert invoices.count() == 3
        states = {invoice.invoice_state for invoice in invoices}
        assert states == {
            AccMove.INVOICE_STATE_DRAFT,
            AccMove.INVOICE_STATE_VALIDATED,
            AccMove.INVOICE_STATE_PAID_PARTIALLY,
        }

        demo_user = User.objects.get(email="comptable.demo@widehalo.local")
        assert demo_user.groups.filter(name="comptable").exists()


def test_seed_accounting_is_idempotent() -> None:
    call_command("seed_accounting", tenant_code="TEST-SEED-ACC-IDEMP")
    call_command("seed_accounting", tenant_code="TEST-SEED-ACC-IDEMP")

    tenant = Tenant.objects.get(code="TEST-SEED-ACC-IDEMP")
    with use_tenant(tenant.id):
        invoices = AccMove.objects.filter(tenant=tenant, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
        assert invoices.count() == 3
        assert AccJournal.objects.filter(tenant=tenant, code="VTE").count() == 1
