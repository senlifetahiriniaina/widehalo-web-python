"""Import des quantites initiales de stock depuis un fichier xlsx — jeu de
donnees synthetique (jamais un fichier reel), cf. docs/IMPORT_FORMATS.md."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest
from openpyxl import Workbook

from apps.catalog.tests.factories import ProductVariantFactory
from apps.core.models.workflow import ApprovalRequest
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkImportRow, StkQuant
from apps.stocks.services.stock_import import (
    ANOMALY_EMPLACEMENT_INCONNU,
    ANOMALY_ENTREPOT_INCONNU,
    ANOMALY_QUANTITE_INVALIDE,
    ANOMALY_VARIANTE_INCONNUE,
    STOCK_IMPORT_FORMAT_VERSION,
    decide_qualification,
    ensure_qualification_approval_rule,
    import_stock_quantities_xlsx,
    qualify_import_row,
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
        assert summary.needs_qualification_count == 0
        assert summary.unresolvable_count == 0

        quant = StkQuant.objects.get(tenant=tenant, variant_id=variant.id, location=location)
        assert quant.qty == Decimal("100.0000")


def test_unknown_variant_and_location_need_qualification_when_warehouse_is_known() -> None:
    """Depuis RG-QUALIF, variante/emplacement inconnus ne bloquent plus la
    ligne tant que l'entrepot est identifie : repli sur les placeholders,
    un `StkMove` VALIDE est materialise immediatement."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        StkWarehouseFactory(tenant=tenant, code="WH1")

    file_bytes = _build_xlsx([[str(uuid.uuid4()), "WH1", "INCONNU", 10, 100, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)

        assert summary.needs_qualification_count == 1
        assert summary.unresolvable_count == 0
        row = StkImportRow.objects.get(batch=summary.batch)
        assert row.status == StkImportRow.STATUS_NEEDS_QUALIFICATION
        assert ANOMALY_VARIANTE_INCONNUE in row.anomaly_codes
        assert ANOMALY_EMPLACEMENT_INCONNU in row.anomaly_codes
        assert row.uses_placeholder_variant is True
        assert row.uses_placeholder_location is True
        assert row.move is not None


def test_unknown_warehouse_is_unresolvable_non_defaultable() -> None:
    """`ENTREPOT_INCONNU` reste non-defaultable — aucun entrepot par
    defaut sûr, aucun `StkMove` n'est cree."""
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["REF-INCONNUE", "WH-INCONNU", "LOC1", 10, 100, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)

        assert summary.unresolvable_count == 1
        row = StkImportRow.objects.get(batch=summary.batch)
        assert row.status == StkImportRow.STATUS_UNRESOLVABLE
        assert ANOMALY_ENTREPOT_INCONNU in row.anomaly_codes
        assert row.move is None


def test_import_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([[str(uuid.uuid4()), "WH1", "LOC1", 10, 100, ""]])

    with use_tenant(tenant.id), pytest.raises(ValueError, match="non supporté"):
        import_stock_quantities_xlsx(
            tenant, file_bytes, format_version=STOCK_IMPORT_FORMAT_VERSION + 1
        )


def test_resolve_unresolvable_row_creates_move_once_quantity_is_fixed() -> None:
    """Seuls les codes non-defaultables restent geres par
    `resolve_import_row` depuis RG-QUALIF — ici une quantite invalide."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
        warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
        location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")

    file_bytes = _build_xlsx([[variant.reference, "WH1", "LOC1", 0, 100, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)
        row = summary.batch.rows.get(row_number=1)
        assert row.status == StkImportRow.STATUS_UNRESOLVABLE
        assert ANOMALY_QUANTITE_INVALIDE in row.anomaly_codes

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


def test_resolve_unresolvable_row_can_be_discarded() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        StkWarehouseFactory(tenant=tenant, code="WH1")

    file_bytes = _build_xlsx([["REF-INCONNUE", "WH-INCONNU", "LOC1", 10, 100, ""]])

    with use_tenant(tenant.id):
        summary = import_stock_quantities_xlsx(tenant, file_bytes)
        row = summary.batch.rows.get(row_number=1)

        resolved = resolve_import_row(row, discard=True)

        assert resolved.status == StkImportRow.STATUS_DISCARDED


def _import_needs_qualification_row(tenant, warehouse) -> StkImportRow:
    file_bytes = _build_xlsx([[str(uuid.uuid4()), warehouse.code, "INCONNU", 10, 100, ""]])
    summary = import_stock_quantities_xlsx(tenant, file_bytes)
    return StkImportRow.objects.get(batch=summary.batch)


class TestQualifyImportRow:
    def test_qualify_reverses_the_placeholder_move_and_creates_a_new_one(self) -> None:
        tenant = TenantFactory()
        with use_tenant(tenant.id):
            variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
            warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
            location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")
            row = _import_needs_qualification_row(tenant, warehouse)
            placeholder_move = row.move
            qualifier = UserFactory()

            qualified = qualify_import_row(
                row, variant_id=variant.id, location=location, qualified_by=qualifier
            )

            assert qualified.status == StkImportRow.STATUS_PENDING_APPROVAL
            assert qualified.uses_placeholder_variant is False
            assert qualified.uses_placeholder_location is False
            assert qualified.resolved_variant_id == variant.id
            assert qualified.resolved_location_id == location.id
            assert qualified.move_id != placeholder_move.id
            quant = StkQuant.objects.get(tenant=tenant, variant_id=variant.id, location=location)
            assert quant.qty == Decimal("10.0000")

    def test_qualify_refuses_without_the_missing_dimensions(self) -> None:
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        with use_tenant(tenant.id):
            warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
            row = _import_needs_qualification_row(tenant, warehouse)
            qualifier = UserFactory()

            with pytest.raises(ValidationError):
                qualify_import_row(row, qualified_by=qualifier)

    def test_qualify_marks_qualified_directly_when_rule_is_inactive(self) -> None:
        tenant = TenantFactory()
        with use_tenant(tenant.id):
            variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
            warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
            location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")
            row = _import_needs_qualification_row(tenant, warehouse)
            qualifier = UserFactory()

            rule = ensure_qualification_approval_rule(tenant)
            rule.is_active = False
            rule.save(update_fields=["is_active"])

            qualified = qualify_import_row(
                row, variant_id=variant.id, location=location, qualified_by=qualifier
            )

            assert qualified.status == StkImportRow.STATUS_QUALIFIED
            assert qualified.qualification_approval_request is None


class TestDecideQualification:
    def test_approving_marks_the_row_qualified(self) -> None:
        tenant = TenantFactory()
        with use_tenant(tenant.id):
            variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
            warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
            location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")
            row = _import_needs_qualification_row(tenant, warehouse)
            qualifier = UserFactory()
            approver = UserFactory()

            qualified = qualify_import_row(
                row, variant_id=variant.id, location=location, qualified_by=qualifier
            )
            assert qualified.status == StkImportRow.STATUS_PENDING_APPROVAL
            request = qualified.qualification_approval_request
            assert ApprovalRequest.objects.filter(id=request.id).exists()

            decided = decide_qualification(request, approver, approved=True)

            assert decided.status == StkImportRow.STATUS_QUALIFIED

    def test_rejecting_returns_the_row_to_needs_qualification(self) -> None:
        tenant = TenantFactory()
        with use_tenant(tenant.id):
            variant = ProductVariantFactory(tenant=tenant, reference="VAR001")
            warehouse = StkWarehouseFactory(tenant=tenant, code="WH1")
            location = StkLocationFactory(tenant=tenant, warehouse=warehouse, code="LOC1")
            row = _import_needs_qualification_row(tenant, warehouse)
            qualifier = UserFactory()
            approver = UserFactory()

            qualified = qualify_import_row(
                row, variant_id=variant.id, location=location, qualified_by=qualifier
            )

            decided = decide_qualification(
                qualified.qualification_approval_request, approver, approved=False, comment="non"
            )

            assert decided.status == StkImportRow.STATUS_NEEDS_QUALIFICATION
