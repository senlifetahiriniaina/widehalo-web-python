"""Import du catalogue (gammes + variantes generees + specs textiles)
depuis un fichier xlsx — jeu de donnees synthetique (jamais un fichier
reel), cf. docs/IMPORT_FORMATS.md."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from apps.catalog.models import ProductTemplate, ProductVariant, TextileSpec, UnitOfMeasure
from apps.catalog.services.catalog_import import CATALOG_FORMAT_VERSION, import_catalog_xlsx
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

_HEADER = [
    "Template_code",
    "Template_name",
    "Category",
    "Uom",
    "Variant_attributes",
    "Material",
    "Composition",
    "Weight_gsm",
    "Width_cm",
]


def _build_xlsx(rows: list[list[object]], *, header: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header or _HEADER)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _create_uom(tenant, code: str = "PC") -> None:
    UnitOfMeasure.objects.create(
        tenant=tenant, code=code, name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
    )


def test_import_creates_template_and_generates_variants() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        _create_uom(tenant)
    file_bytes = _build_xlsx(
        [
            [
                "TMPL001",
                "T-shirt",
                "Vetements",
                "PC",
                "Couleur=Rouge;Taille=M",
                "Coton",
                "100% coton",
                180,
                150,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_catalog_xlsx(tenant, file_bytes, filename="catalogue.xlsx")

        assert summary.is_valid
        assert summary.created_count == 1
        template = ProductTemplate.objects.get(tenant=tenant, reference="TMPL001")
        assert template.category.name == "Vetements"
        variants = ProductVariant.objects.filter(tenant=tenant, template=template)
        assert variants.count() == 1
        assert summary.variants_created_count == 1
        assert summary.textile_specs_created_count == 1
        spec = TextileSpec.objects.get(variant=variants.first())
        assert spec.material == "Coton"


def test_import_is_idempotent_by_template_code() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        _create_uom(tenant)
    file_bytes = _build_xlsx([["TMPL001", "T-shirt", "", "PC", "", "", "", None, None]])

    with use_tenant(tenant.id):
        import_catalog_xlsx(tenant, file_bytes)
        summary = import_catalog_xlsx(tenant, file_bytes)

        assert summary.created_count == 0
        assert summary.skipped_existing_count == 1
        assert ProductTemplate.objects.filter(tenant=tenant, reference="TMPL001").count() == 1


def test_import_rejects_unknown_uom_without_writing_anything() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["TMPL001", "T-shirt", "", "INCONNU", "", "", "", None, None]])

    with use_tenant(tenant.id):
        summary = import_catalog_xlsx(tenant, file_bytes)

        assert not summary.is_valid
        assert len(summary.row_errors) == 1
        assert "uom" in summary.row_errors[0].errors
        assert not ProductTemplate.objects.filter(tenant=tenant).exists()


def test_import_rejects_more_than_two_generator_attributes() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        _create_uom(tenant)
    file_bytes = _build_xlsx(
        [
            [
                "TMPL001",
                "T-shirt",
                "",
                "PC",
                "Couleur=Rouge;Taille=M;Matiere=Coton",
                "",
                "",
                None,
                None,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_catalog_xlsx(tenant, file_bytes)

        assert not summary.is_valid
        assert not ProductTemplate.objects.filter(tenant=tenant).exists()


def test_import_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        _create_uom(tenant)
    file_bytes = _build_xlsx([["TMPL001", "T-shirt", "", "PC", "", "", "", None, None]])

    with use_tenant(tenant.id):
        with pytest.raises(ValueError, match="non supporté"):
            import_catalog_xlsx(tenant, file_bytes, format_version=CATALOG_FORMAT_VERSION + 1)
        assert not ProductTemplate.objects.filter(tenant=tenant).exists()


def test_import_accepts_canonical_header_aliases() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        _create_uom(tenant)
    file_bytes = _build_xlsx(
        [["TMPL002", "Pantalon", "", "PC", "", "", "", None, None]],
        header=[
            "TEMPLATE_CODE",
            "TEMPLATE_NAME",
            "CATEGORY",
            "UOM",
            "VARIANT_ATTRIBUTES",
            "MATERIAL",
            "COMPOSITION",
            "WEIGHT_GSM",
            "WIDTH_CM",
        ],
    )

    with use_tenant(tenant.id):
        summary = import_catalog_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 1
