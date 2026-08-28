"""Import des quantites initiales de stock depuis un fichier xlsx — jeu de
donnees synthetique (jamais un fichier reel), cf. docs/IMPORT_FORMATS.md."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest
from openpyxl import Workbook

from apps.catalog.tests.factories import ProductVariantFactory
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkImportRow, StkQuant
from apps.stocks.services.stock_import import (
    ANOMALY_EMPLACEMENT_INCONNU,
    ANOMALY_VARIANTE_INCONNUE,
    STOCK_IMPORT_FORMAT_VERSION,
    import_stock_quantities_xlsx,
    resolve_import_row,
)
from apps.stocks.tests.factories import StkLocationFactory, StkWarehouseFactory

pytestmark = pytest.mark.django_db

_HEADER = [
    "Variant_code",
    "Warehouse_code",
    "Location_code",
    "Qty",
    "Unit_cost_mga",
    "Lot_reference",
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


def test_import_creates_validated_moves_and_quants() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
        warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
        location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")

    file_bytes = _build_xlsx([[variant.reference, "WH1", "LOC1", 100, 500, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes, filename="stock.xlsx")

        assert summary.total_rows == 1
        assert summary.ok_count == 1
        assert summary.anomaly_count == 0

        quant = StkQuant.objects.get(tenant=tenant, variant_id=variant.id, location=location)
        assert quant.qty == Decimal("100.0000")


def test_import_reports_anomaly_for_unknown_variant_and_location() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        StkWarehouseFactory(tenant=tenant, code="WH1")

    file_bytes = _build_xlsx(
        [
            [str(uuid.uuid4()), "WH1", "INCONNU", 10, 100, ""],
            ["REF-INCONNUE", "WH-INCONNU", "LOC1", 10, 100, ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)

        assert summary.total_rows == 2
        assert summary.anomaly_count == 2
        rows = StkImportRow.objects.filter(batch=summary.batch).order_by("row_number")
        assert ANOMALY_VARIANTE_INCONNUE in rows[0].anomaly_codes
        assert ANOMALY_EMPLACEMENT_INCONNU in rows[0].anomaly_codes
        assert ANOMALY_VARIANTE_INCONNUE in rows[1].anomaly_codes


def test_import_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([[str(uuid.uuid4()), "WH1", "LOC1", 10, 100, ""]])

    with use_tenant(tenant.id), pytest.raises(ValueError, match="non supporté"):
        import_stock_quantities_xlsx(
            tenant, file_bytes, format_version=STOCK_IMPORT_FORMAT_VERSION + 1
        )


def test_resolve_anomaly_row_creates_move() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
        warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
        location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")

    file_bytes = _build_xlsx([["REF-INCONNUE", "WH1", "LOC1", 10, 100, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)
        row = summary.batch.rows.get(row_number=1)
        assert row.status == StkImportRow.STATUS_ANOMALY

        resolved = resolve_import_row(
            row,
            variant_code=variant.reference,
            warehouse=warehouse,
            location=location,
            qty=Decimal(10),
        )

        assert resolved.status == StkImportRow.STATUS_RESOLVED
        assert resolved.move is not None
        quant = StkQuant.objects.get(tenant=tenant, variant_id=variant.id, location=location)
        assert quant.qty == Decimal("10.0000")


def test_resolve_anomaly_row_can_be_discarded() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        StkWarehouseFactory(tenant=tenant, code="WH1")

    file_bytes = _build_xlsx([["REF-INCONNUE", "WH1", "LOC1", 10, 100, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)
        row = summary.batch.rows.get(row_number=1)

        resolved = resolve_import_row(row, discard=True)

        assert resolved.status == StkImportRow.STATUS_DISCARDED
