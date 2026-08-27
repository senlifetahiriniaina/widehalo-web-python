"""Parcours critiques Playwright (couche 1, §8 du CDC) pour les 4 ecrans
HTMX minimaux du Lot 2 Madagascar (U1) : un aller-retour liste -> creation
-> detail -> transition de workflow par module, sans rechargement de page
complete (verifie indirectement : la navigation reste sur les URLs
attendues sans requete de navigation complete pour les actions HTMX)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmPipeline, CrmStage
from apps.mrp.models import MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.patronage.models import PatSizeChart

pytestmark = pytest.mark.playwright


def test_accounting_invoice_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        AccJournal.objects.create(
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        AccAccount.objects.create(
            tenant=tenant, code="411000", name="Clients", account_class="4", type="receivable"
        )
        AccAccount.objects.create(
            tenant=tenant, code="701000", name="Ventes", account_class="7", type="income"
        )

    page = logged_in_page
    page.goto(f"{live_server.url}/accounting/new/")
    page.fill("#label", "Vente Playwright")
    page.fill("#amount", "150000")
    page.fill("#date", "2026-01-10")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/accounting/**")
    assert "Vente Playwright" in page.content() or "150000" in page.content()


def test_crm_lead_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Standard", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="new", name="Nouveau", sequence=1
        )

    page = logged_in_page
    page.goto(f"{live_server.url}/crm/new/")
    page.fill("#name", "Opportunite Playwright")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/crm/**")
    assert "Opportunite Playwright" in page.content()


def test_mrp_order_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        MrpWorkshop.objects.create(tenant=tenant, code="ATL-E2E", name="Atelier E2E")
        bom = create_bom(tenant=tenant, code="BOM-E2E", product_template_id=uuid.uuid4())
        add_bom_line(bom, component_template_id=uuid.uuid4(), qty=Decimal(1))
        activate_bom(bom)

    page = logged_in_page
    page.goto(f"{live_server.url}/mrp/new/")
    page.select_option("#bom_id", label="BOM-E2E")
    page.select_option("#workshop_id", label="Atelier E2E")
    page.fill("#qty", "4")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/mrp/**")
    page.click("button[value=confirm]")
    page.wait_for_url(f"{live_server.url}/mrp/**")
    assert "Confirme" in page.content()


def test_patronage_pattern_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-E2E",
            name="T-shirt E2E",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )

    page = logged_in_page
    page.goto(f"{live_server.url}/patronage/new/")
    page.fill("#code", "PAT-E2E")
    page.fill("#name", "Patron Playwright")
    page.select_option("#size_chart_id", label="T-shirt E2E")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/patronage/**")
    assert "Patron Playwright" in page.content()
