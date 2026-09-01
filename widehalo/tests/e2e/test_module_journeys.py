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
from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
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


def test_sales_quotation_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    """Comble le trou identifie lors du retest des 14 couches (§8) : `sales`
    n'existait pas encore lors de la premiere passe (U1/U2) — un partenaire
    est un simple UUID (regle de couplage n1), aucune donnee de config
    prealable requise contrairement a `accounting`/`mrp`."""
    page = logged_in_page
    page.goto(f"{live_server.url}/sales/new/")
    # `#partner_id` est le champ cache du composant reutilisable
    # `_partner_picker.html` (UXR3/UXR5) : jamais rempli via l'UI de recherche
    # instantanee dans ce parcours (deja couverte par les tests dedies
    # UXR3/UXR5), seule la valeur finale soumise au formulaire nous
    # interesse ici — on la pose directement, comme le ferait une vraie
    # selection de partenaire dans le picker.
    page.evaluate(
        "(value) => { document.querySelector('#partner_id').value = value; }",
        str(uuid.uuid4()),
    )
    page.fill("#date", "2026-01-10")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/sales/**")
    page.click("button[value=send]")
    page.wait_for_url(f"{live_server.url}/sales/**")
    assert "Envoye" in page.content() or "Sent" in page.content()


def test_purchase_requisition_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    """Meme raisonnement que `sales` ci-dessus : `purchase` n'existait pas
    encore lors de la premiere passe. Parcours sur `PurRequisition` (PU1,
    la brique la plus simple du module — pas de FSM `django-fsm`, deux
    transitions triviales), plutot que `PurOrder` qui exigerait de creer un
    fournisseur/une regle d'approbation."""
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        # `add_requisition_line` resout un prix indicatif via
        # `catalog.services.public.get_variant_price`, qui exige une
        # variante REELLEMENT existante (pas un UUID nu comme pour
        # `sales`/`crm` — regle de couplage n1 non applicable ici, l'article
        # d'une demande d'achat est un vrai `ProductVariant`).
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="M-E2E", name="Metre E2E", category=UnitOfMeasure.CATEGORY_LENGTH
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Fil polyester E2E",
            base_uom=uom,
            reference="TPL-PUR-E2E-0001",
            base_price_mga=Decimal("2000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-E2E-0001"
        )

    page = logged_in_page
    page.goto(f"{live_server.url}/purchase/requisitions/new/")
    page.fill("#department", "Production")
    page.fill("#date_needed", "2026-02-01")
    page.fill("#justification", "Reapprovisionnement fil polyester")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/purchase/requisitions/**")
    # `submit_requisition` (RG-PUR-1) refuse une demande sans ligne — ajouter
    # une ligne d'abord, meme discipline que
    # `tests/ui/test_purchase_screens.py`.
    page.fill("#variant_id", str(variant.id))
    page.fill("#description", "Fil polyester")
    page.click("button:has-text('Ajouter')")
    page.wait_for_url(f"{live_server.url}/purchase/requisitions/**")
    page.click("button[value=submit]")
    page.wait_for_url(f"{live_server.url}/purchase/requisitions/**")
    assert "Soumise" in page.content() or "Submitted" in page.content()


def test_stocks_move_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    """`stocks` n'a pas d'ecran de creation dedie (formulaire imbrique
    directement dans l'onglet "Mouvements" de l'ecran unique `/stocks/`,
    cf. `templates/stocks/index.html`) — meme parcours que
    `tests/ui/test_stocks_screens.py::test_move_list_create_detail_
    validate_round_trip`, rejoue ici en conditions navigateur reelles."""
    tenant, _user = e2e_tenant_and_user
    with use_tenant(tenant.id):
        from apps.stocks.services.warehouses import create_location, create_warehouse

        warehouse = create_warehouse(tenant=tenant, code="WH-E2E", name="Entrepot E2E")
        create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS-E2E",
            name="Fournisseur E2E",
            type="fournisseur",
        )
        create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1-E2E",
            name="Rayon A1 E2E",
            type="interne",
        )

    page = logged_in_page
    page.goto(f"{live_server.url}/stocks/moves/")
    page.fill("input[name=variant_id]", str(uuid.uuid4()))
    page.fill("input[name=qty]", "10")
    page.select_option("select[name=location_from_id]", label="FRS-E2E")
    page.select_option("select[name=location_to_id]", label="A1-E2E")
    page.click("button[type=submit]")
    # `create_move` redirige vers la LISTE (`stocks:move_list`), pas vers le
    # detail — ouvrir le mouvement fraichement cree (le seul de ce tenant)
    # avant de le valider, meme parcours que
    # `tests/ui/test_stocks_screens.py::test_move_list_create_detail_
    # validate_round_trip`.
    page.wait_for_url(f"{live_server.url}/stocks/moves/")
    page.click("text=Ouvrir")
    page.wait_for_url(f"{live_server.url}/stocks/moves/**")
    page.click("button[value=validate]")
    page.wait_for_url(f"{live_server.url}/stocks/moves/**")
    assert "Valide" in page.content() or "Done" in page.content() or "done" in page.content()


def test_logistics_shipment_journey(logged_in_page, live_server, e2e_tenant_and_user) -> None:
    """Meme raisonnement que `sales`/`purchase` ci-dessus."""
    page = logged_in_page
    page.goto(f"{live_server.url}/logistics/shipments/new/")
    page.fill("#origin", "Guangzhou")
    page.fill("#destination", "Toamasina")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/logistics/shipments/**")
    page.click("button[value=book]")
    page.wait_for_url(f"{live_server.url}/logistics/shipments/**")
    assert "Reservee" in page.content() or "Booked" in page.content()
