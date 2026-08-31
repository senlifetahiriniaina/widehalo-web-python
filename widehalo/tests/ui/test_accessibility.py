from __future__ import annotations

import pytest
from apps.accounting.models import AccMove
from apps.accounting.tests.factories import AccMoveFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.tests.factories import CrmLeadFactory
from apps.feasibility.tests.factories import FeaStudyFactory
from apps.financing.tests.factories import FinLoanApplicationFactory
from apps.mrp.tests.factories import MrpOrderFactory
from apps.patronage.tests.factories import PatPatternFactory
from apps.purchase.tests.factories import PurOrderFactory
from apps.sales.tests.factories import SalesOrderFactory
from apps.stocks.tests.factories import StkMoveFactory
from apps.strategy.tests.factories import StgObjectiveFactory
from bs4 import BeautifulSoup
from django.test import Client

pytestmark = pytest.mark.django_db


def _logged_in_client() -> tuple[Client, Tenant]:
    tenant = Tenant.objects.create(code="UI-A11Y", name="UI A11y Tenant")
    user = User.objects.create_user(email="ui-a11y@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def _assert_all_fields_labelled(soup: BeautifulSoup, screen: str) -> None:
    """Tout champ de formulaire visible doit porter un `<label for=...>`
    associe ou un `aria-label` — regle reutilisee par les 3 ecrans d'origine
    et par l'echantillon etendu ci-dessous (RG UI1-3, audit accessibilite)."""
    labelled_ids = {label.get("for") for label in soup.find_all("label") if label.get("for")}
    for field in soup.find_all(["input", "select", "textarea"]):
        if field.get("type") in {"hidden", "csrfmiddlewaretoken"}:
            continue
        # Un champ englobe par un <label> (label implicite, ex.
        # `<label><input type="checkbox"> Texte</label>`) est aussi valide
        # au sens WCAG — pas seulement le `<label for="...">` explicite.
        wrapped_by_label = field.find_parent("label") is not None
        assert field.get("id") in labelled_ids or field.get("aria-label") or wrapped_by_label, (
            f"[{screen}] champ sans label associe : {field}"
        )


def _assert_icon_only_controls_have_accessible_name(soup: BeautifulSoup, screen: str) -> None:
    """Un bouton/lien dont le seul contenu visible est un symbole (pas de
    texte) doit porter un `aria-label` explicite — sinon un lecteur d'ecran
    n'a rien a annoncer."""
    for control in soup.find_all(["button", "a"]):
        text = control.get_text(strip=True)
        has_visible_text = bool(text)
        if has_visible_text or control.get("aria-label") or control.find("span", class_="sr-only"):
            continue
        # Un controle totalement vide (pas d'icone non plus) n'est pas un
        # controle icone-seule au sens de cet audit — ignore.
        if not control.contents:
            continue
        pytest.fail(f"[{screen}] controle icone-seule sans nom accessible : {control}")


def test_dashboard_declares_a_language() -> None:
    client, _tenant = _logged_in_client()
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    assert soup.html is not None
    assert soup.html.get("lang")


def test_login_page_inputs_all_have_labels() -> None:
    soup = BeautifulSoup(Client().get("/login/").content, "html.parser")
    _assert_all_fields_labelled(soup, "login")


def test_search_page_input_has_a_label() -> None:
    client, _tenant = _logged_in_client()
    soup = BeautifulSoup(client.get("/search/").content, "html.parser")
    labelled_ids = {label.get("for") for label in soup.find_all("label") if label.get("for")}
    # id="instant-search" identifies the search page's own input, distinct from the
    # topbar's always-present "topbar-search" input (which uses aria-label instead
    # of a <label for>, also a valid accessible name, cf. test below).
    search_input = soup.find("input", {"name": "q", "id": "instant-search"})
    assert search_input is not None
    assert search_input.get("id") in labelled_ids


def test_topbar_search_input_has_an_accessible_name() -> None:
    client, _tenant = _logged_in_client()
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    topbar_search = soup.find("input", {"id": "topbar-search"})
    assert topbar_search is not None
    assert topbar_search.get("aria-label")


# --- Audit accessibilite etendu (UI1-3) : echantillon representatif -------
#
# Au-dela des 3 ecrans historiques ci-dessus, on couvre au moins un ecran de
# liste et un ecran de detail pour un echantillon representatif des modules
# metier (10 modules avec un couple liste/detail simple a instancier via une
# factory existante, + 3 ecrans a vue unique deja significatifs). Ce n'est
# pas une revue exhaustive des ~160 templates — conformement au cadrage du
# chantier — mais un echantillon suffisant pour deceler les problemes reels
# (labels manquants, controles icone-seule sans nom accessible).


def test_accounting_invoice_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        invoice = AccMoveFactory(tenant=tenant, move_type=AccMove.TYPE_CUSTOMER_INVOICE)

    for label, url in (
        ("accounting:list", "/accounting/"),
        ("accounting:detail", f"/accounting/{invoice.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_crm_lead_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        lead = CrmLeadFactory(tenant=tenant)

    for label, url in (
        ("crm:list", "/crm/"),
        ("crm:detail", f"/crm/{lead.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_mrp_order_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        order = MrpOrderFactory(tenant=tenant)

    for label, url in (
        ("mrp:list", "/mrp/"),
        ("mrp:detail", f"/mrp/{order.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_sales_order_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        order = SalesOrderFactory(tenant=tenant)

    for label, url in (
        ("sales:order_list", "/sales/orders/"),
        ("sales:order_detail", f"/sales/orders/{order.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_purchase_order_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        order = PurOrderFactory(tenant=tenant)

    for label, url in (
        ("purchase:order_list", "/purchase/orders/"),
        ("purchase:order_detail", f"/purchase/orders/{order.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_stocks_move_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        move = StkMoveFactory(tenant=tenant)

    for label, url in (
        ("stocks:move_list", "/stocks/moves/"),
        ("stocks:move_detail", f"/stocks/moves/{move.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_patronage_pattern_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        pattern = PatPatternFactory(tenant=tenant)

    for label, url in (
        ("patronage:list", "/patronage/"),
        ("patronage:detail", f"/patronage/{pattern.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_feasibility_study_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        study = FeaStudyFactory(tenant=tenant)

    for label, url in (
        ("feasibility:list", "/feasibility/"),
        ("feasibility:detail", f"/feasibility/{study.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_strategy_objective_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        objective = StgObjectiveFactory(tenant=tenant)

    for label, url in (
        ("strategy:list", "/strategy/"),
        ("strategy:detail", f"/strategy/{objective.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_financing_loan_application_list_and_detail_are_accessible() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        application = FinLoanApplicationFactory(tenant=tenant)

    for label, url in (
        ("financing:list", "/financing/"),
        ("financing:detail", f"/financing/{application.id}/"),
    ):
        soup = BeautifulSoup(client.get(url).content, "html.parser")
        _assert_all_fields_labelled(soup, label)
        _assert_icon_only_controls_have_accessible_name(soup, label)


def test_presence_dashboard_is_accessible() -> None:
    client, _tenant = _logged_in_client()
    soup = BeautifulSoup(client.get("/presence/").content, "html.parser")
    _assert_all_fields_labelled(soup, "presence:dashboard")
    _assert_icon_only_controls_have_accessible_name(soup, "presence:dashboard")


def test_payroll_my_payslips_is_accessible() -> None:
    client, _tenant = _logged_in_client()
    soup = BeautifulSoup(client.get("/payroll/").content, "html.parser")
    _assert_all_fields_labelled(soup, "payroll:my_payslips")
    _assert_icon_only_controls_have_accessible_name(soup, "payroll:my_payslips")


def test_reporting_catalog_is_accessible() -> None:
    client, _tenant = _logged_in_client()
    soup = BeautifulSoup(client.get("/reporting/").content, "html.parser")
    _assert_all_fields_labelled(soup, "reporting:catalog")
    _assert_icon_only_controls_have_accessible_name(soup, "reporting:catalog")
