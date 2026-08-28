"""Import du referentiel partenaires depuis un fichier xlsx — jeu de
donnees synthetique (jamais un fichier reel), cf. docs/IMPORT_FORMATS.md."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.partner_import import (
    PARTNER_FORMAT_VERSION,
    import_partners_xlsx,
)

pytestmark = pytest.mark.django_db


def _build_xlsx(rows: list[list[object]], *, header: list[str] | None = None) -> bytes:
    header = header or [
        "Code",
        "Nom",
        "NIF",
        "Roles",
        "Credit_limit_mga",
        "Email",
        "Phone",
        "Address",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_creates_partners_with_role_translation() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client SARL", "NIF001", "client", 500000, "", "", ""],
            ["P002", "Fournisseur Textile", "NIF002", "fournisseur;transporteur", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes, filename="partenaires.xlsx")

        assert summary.is_valid
        assert summary.created_count == 2
        assert summary.skipped_existing_count == 0

        client_partner = Partner.objects.get(tenant=tenant, reference="P001")
        assert client_partner.roles == [Partner.ROLE_CLIENT]
        supplier_partner = Partner.objects.get(tenant=tenant, reference="P002")
        assert supplier_partner.roles == [Partner.ROLE_SUPPLIER, Partner.ROLE_CARRIER]


def test_import_is_idempotent_by_code() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["P001", "Client SARL", "", "client", 0, "", "", ""]])

    with use_tenant(tenant.id):
        import_partners_xlsx(tenant, file_bytes)
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.created_count == 0
        assert summary.skipped_existing_count == 1
        assert Partner.objects.filter(tenant=tenant, reference="P001").count() == 1


def test_import_flags_duplicate_nif_without_blocking() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client A", "SAMENIF", "client", 0, "", "", ""],
            ["P002", "Client B (doublon NIF)", "SAMENIF", "client", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 2
        assert summary.duplicate_alerts_count == 1
        assert DuplicateAlert.objects.filter(tenant=tenant).count() == 1


def test_import_reports_row_errors_without_writing_anything() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["P001", "Client valide", "", "client", 0, "", "", ""],
            # Role inconnu -> ArrayField choices invalide -> row error.
            ["P002", "Client invalide", "", "role_invalide", 0, "", "", ""],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert not summary.is_valid
        assert len(summary.row_errors) == 1
        assert summary.row_errors[0].row_index == 1
        assert not Partner.objects.filter(tenant=tenant).exists()


def test_import_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["P001", "Client", "", "client", 0, "", "", ""]])

    with use_tenant(tenant.id):
        with pytest.raises(ValueError, match="non supporté"):
            import_partners_xlsx(tenant, file_bytes, format_version=PARTNER_FORMAT_VERSION + 1)
        assert not Partner.objects.filter(tenant=tenant).exists()


def test_import_accepts_canonical_header_aliases_and_ignores_coordinates() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [["P010", "Client", "", "client", 0, "client@example.com", "0340000000", "Antananarivo"]],
        header=["CODE", "NAME", "NIF", "ROLES", "CREDIT_LIMIT_MGA", "EMAIL", "PHONE", "ADDRESS"],
    )

    with use_tenant(tenant.id):
        summary = import_partners_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 1
        assert summary.coordinates_ignored_count == 1
