from __future__ import annotations

from decimal import Decimal

import pytest
from apps.catalog.models import ProductTemplate, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.core.views.smart_table import smart_table_dom_id
from apps.partners.models import Partner
from django.test import Client

pytestmark = pytest.mark.django_db


def _logged_in_client() -> tuple[Client, Tenant]:
    tenant = Tenant.objects.create(code="UI-TABLE", name="UI Table Tenant")
    user = User.objects.create_user(email="ui-table@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def test_search_filters_rows() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Textiles Alpha", reference="PART-0001")
        Partner.objects.create(tenant=tenant, name="Beta Confection", reference="PART-0002")

    response = client.get("/partners/", {"q": "Alpha"})
    body = response.content.decode()
    assert "Textiles Alpha" in body
    assert "Beta Confection" not in body


def test_csv_export_returns_a_csv_response() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Gamma", reference="PART-0003")

    response = client.get("/partners/", {"export": "csv"})
    assert response["Content-Type"] == "text/csv"
    assert b"Gamma" in response.content or b"PART-0003" in response.content


def test_csv_export_is_independent_of_page_size() -> None:
    """L'export CSV interroge le queryset complet AVANT pagination — jamais
    limite par `page_size`, meme une valeur volontairement petite."""
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(30):
            Partner.objects.create(tenant=tenant, name=f"Export {i}", reference=f"EXP-{i:04d}")

    response = client.get("/partners/", {"export": "csv", "page_size": "25"})
    body = response.content.decode()
    assert body.count("EXP-") == 30


def test_hidden_columns_are_not_rendered() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Delta", reference="PART-0004", nif="NIF-XYZ")

    response = client.get("/partners/", {"hide": "nif"})
    body = response.content.decode()
    assert "NIF-XYZ" not in body


def test_pagination_limits_rows_per_page() -> None:
    """Taille de page par defaut = 25 (remplace l'ancien defaut de 20)."""
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(30):
            Partner.objects.create(tenant=tenant, name=f"Partner {i}", reference=f"PART-{i:04d}")

    response = client.get("/partners/")
    body = response.content.decode()
    assert body.count("PART-") == 25


def test_page_size_selector_accepts_allowed_values() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(60):
            Partner.objects.create(tenant=tenant, name=f"Sized {i}", reference=f"SZ-{i:04d}")

    response = client.get("/partners/", {"page_size": "50"})
    body = response.content.decode()
    assert body.count("SZ-") == 50


def test_page_size_selector_rejects_unknown_value() -> None:
    """Une taille de page hors de `ALLOWED_PAGE_SIZES` retombe silencieusement
    sur le defaut (25) — jamais une valeur arbitraire non bornee."""
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(30):
            Partner.objects.create(tenant=tenant, name=f"Bad {i}", reference=f"BAD-{i:04d}")

    response = client.get("/partners/", {"page_size": "999"})
    body = response.content.decode()
    assert body.count("BAD-") == 25


def test_htmx_pagination_next_page_returns_real_page_two_content() -> None:
    """Correctif systemique : l'id du conteneur derive de `table_key` doit
    etre CSS-safe (jamais un point litteral, qui casse silencieusement
    hx-target/hx-select) — verifie la vraie requete fragment HTMX, pas un
    simple `client.get()` sans en-tete."""
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        for i in range(30):
            Partner.objects.create(tenant=tenant, name=f"Htmx {i:02d}", reference=f"HTX-{i:04d}")

    expected_dom_id = smart_table_dom_id("partners.list")
    assert expected_dom_id == "smart-table-partners-list"

    page1 = client.get("/partners/", HTTP_HX_REQUEST="true")
    body1 = page1.content.decode()
    assert f'id="{expected_dom_id}"' in body1
    # L'ancienne forme cassee (point litteral dans l'id) ne doit plus jamais
    # apparaitre.
    assert 'id="smart-table-partners.list"' not in body1
    assert body1.count("HTX-") == 25

    page2 = client.get("/partners/", {"page": "2"}, HTTP_HX_REQUEST="true")
    body2 = page2.content.decode()
    assert f'id="{expected_dom_id}"' in body2
    assert body2.count("HTX-") == 5
    # Le contenu de la page 2 est reellement different de la page 1.
    assert body1 != body2


def test_page_size_selector_lives_next_to_pagination_not_in_the_toolbar() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="Solo", reference="SOLO-0001")

    response = client.get("/partners/")
    body = response.content.decode()
    pagination_idx = body.index('class="pagination"')
    select_idx = body.index('name="page_size"')
    toolbar_idx = body.index('class="smart-table-toolbar')
    # Le selecteur de taille de page apparait dans le bloc <nav
    # class="pagination">, jamais dans la barre d'outils du haut.
    assert select_idx > pagination_idx
    export_links_idx = body.index("Exporter CSV")
    assert toolbar_idx < export_links_idx < select_idx


def test_xlsx_export_returns_a_valid_workbook() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="XlsxPartner", reference="XLS-0001")

    response = client.get("/partners/", {"export": "xlsx"})
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response["Content-Disposition"] == 'attachment; filename="partners.list.xlsx"'
    assert response.content.startswith(b"PK")  # signature ZIP/XLSX


def test_pdf_export_returns_a_pdf_with_company_header_and_widehalo_footer() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        Partner.objects.create(tenant=tenant, name="PdfPartner", reference="PDF-0001")

    response = client.get("/partners/", {"export": "pdf"})
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'attachment; filename="partners.list.pdf"'
    assert response.content.startswith(b"%PDF")

    from io import BytesIO

    import pdfplumber

    with pdfplumber.open(BytesIO(response.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    # Entete = nom de l'entreprise (tenant), pied de page = "WideHalo".
    assert tenant.name in text
    assert "WideHalo" in text


def test_money_column_is_right_aligned() -> None:
    """Prix catalogue (format="mga") doit porter la classe CSS
    d'alignement a droite — jamais le texte brut Decimal sans separateur."""
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PCS", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        ProductTemplate.objects.create(
            tenant=tenant,
            name="Test",
            reference="PT-0001",
            base_price_mga=Decimal("98610.0000"),
            base_uom=uom,
        )

    response = client.get("/catalog/templates/")
    body = response.content.decode()
    # format_mga() utilise deliberement une espace insecable (\xa0) comme
    # separateur de milliers (cf. sa docstring) — jamais une espace normale.
    assert "98\xa0610\xa0Ar" in body
    assert 'class="col-num"' in body


def test_boolean_column_renders_oui_non_not_python_bool() -> None:
    client, tenant = _logged_in_client()
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PCS2", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        ProductTemplate.objects.create(
            tenant=tenant, name="Sellable", reference="PT-0002", is_sellable=True, base_uom=uom
        )
        ProductTemplate.objects.create(
            tenant=tenant, name="Internal", reference="PT-0003", is_sellable=False, base_uom=uom
        )

    response = client.get("/catalog/templates/")
    body = response.content.decode()
    assert "Oui" in body
    assert "Non" in body
    assert ">True<" not in body
    assert ">False<" not in body
