"""Import du plan comptable adapte d'une entreprise depuis un fichier xlsx
fourni par l'utilisateur — jamais les fichiers reels de l'utilisateur, un
jeu synthetique reproduisant fidelement la forme des colonnes reelles
(cf. docs/IMPORT_FORMATS.md)."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from apps.accounting.models import AccAccount, AccCashCategoryMapping
from apps.accounting.services.chart_of_accounts_import import (
    CHART_OF_ACCOUNTS_FORMAT_VERSION,
    import_chart_of_accounts_xlsx,
)
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _build_xlsx(rows: list[list[object]], *, header: list[str] | None = None) -> bytes:
    header = header or [
        "Classe PCG",
        "N° de compte proposé",
        "Intitulé du compte (PCG 2005)",
        "Nature",
        "Catégorie de caisse LIFE MDG",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_creates_accounts_and_category_mappings() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["6", "601", "Achats de matières premières", "Charge", "Achat de matières premières"],
            ["7", "707", "Ventes de marchandises", "Produit", "Vente au comptant"],
            ["5", "571", "Caisse", "Trésorerie", None],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_chart_of_accounts_xlsx(tenant, file_bytes, filename="pcg.xlsx")

        assert summary.is_valid
        assert summary.created_count == 3
        assert summary.skipped_existing_count == 0
        assert summary.category_mappings_count == 2

        account_601 = AccAccount.objects.get(tenant=tenant, code="601")
        assert account_601.type == AccAccount.TYPE_EXPENSE
        account_707 = AccAccount.objects.get(tenant=tenant, code="707")
        assert account_707.type == AccAccount.TYPE_INCOME
        account_571 = AccAccount.objects.get(tenant=tenant, code="571")
        assert account_571.type == AccAccount.TYPE_CASH

        mapping = AccCashCategoryMapping.objects.get(
            tenant=tenant, category_label="Achat de matières premières"
        )
        assert mapping.account == account_601


def test_import_is_idempotent_by_code() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["6", "601", "Achats", "Charge", None]])

    with use_tenant(tenant.id):
        import_chart_of_accounts_xlsx(tenant, file_bytes)

        summary = import_chart_of_accounts_xlsx(tenant, file_bytes)

        assert summary.created_count == 0
        assert summary.skipped_existing_count == 1
        assert AccAccount.objects.filter(tenant=tenant, code="601").count() == 1


def test_import_reports_row_errors_without_writing_anything() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            ["6", "601", "Achats de matières premières", "Charge", None],
            # Ligne invalide : classe non numerique -> account_class ne
            # peut pas etre valide, aucun type reconnu non plus.
            ["4/1", "467/16", "Remboursement d'emprunt", "Nature inconnue", None],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_chart_of_accounts_xlsx(tenant, file_bytes)

        assert not summary.is_valid
        assert len(summary.row_errors) == 1
        assert summary.row_errors[0].row_index == 1
        assert not AccAccount.objects.filter(tenant=tenant).exists()


def test_import_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx([["6", "601", "Achats", "Charge", None]])

    with use_tenant(tenant.id):
        with pytest.raises(ValueError, match="non supporté"):
            import_chart_of_accounts_xlsx(
                tenant, file_bytes, format_version=CHART_OF_ACCOUNTS_FORMAT_VERSION + 1
            )

        assert not AccAccount.objects.filter(tenant=tenant).exists()


def test_import_accepts_canonical_header_aliases() -> None:
    """Un fichier utilisant les libellés canoniques documentés (plutôt que
    ceux du fichier réel de référence) doit être accepté à l'identique —
    c'est le mécanisme de compatibilité ascendante par alias."""
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        # Colonne TYPE canonique : valeur d'enum reelle attendue (AccAccount.TYPE_EXPENSE),
        # pas un libelle descriptif "Nature" (celui-ci n'est accepte qu'en repli).
        [["6", "601", "Achats", AccAccount.TYPE_EXPENSE, None]],
        header=["CLASSE", "CODE", "NAME", "TYPE", "CATEGORIE_CAISSE"],
    )

    with use_tenant(tenant.id):
        summary = import_chart_of_accounts_xlsx(tenant, file_bytes)

        assert summary.is_valid
        assert summary.created_count == 1
