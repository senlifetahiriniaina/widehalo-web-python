"""Import du journal de caisse depuis un fichier xlsx — jeu synthetique
reproduisant fidelement la forme des colonnes reelles (jamais les fichiers
reels de l'utilisateur, cf. docs/IMPORT_FORMATS.md), un scenario par code
d'anomalie reellement observe dans le fichier de reference (montant entree
ET sortie simultane, date aberrante, etc.)."""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from apps.accounting.models import AccAccount, AccImportRow, AccJournal, AccMove
from apps.accounting.services.cash_journal_import import (
    ANOMALY_CATEGORIE_NON_MAPPEE,
    ANOMALY_DATE_INVALIDE,
    ANOMALY_MONTANT_ENTREE_ET_SORTIE,
    ANOMALY_MONTANT_NUL,
    CASH_JOURNAL_FORMAT_VERSION,
    import_cash_journal_xlsx,
    resolve_import_row,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccCashCategoryMappingFactory,
    AccFiscalYearFactory,
    AccJournalFactory,
    AccPeriodFactory,
)
from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

HEADER = [
    "DATE",
    "CAISSE",
    "CATEGORIE",
    "EXCLU DES TOTAUX (solde periode)",
    "CODE PCG DETECTE",
    "LIBELLE",
    "ENTREE",
    "SORTIE",
]


def _build_xlsx(rows: list[list[object]], *, header: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header or HEADER)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def cash_setup():
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        cash_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_CASH, code="571")
        expense_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE, code="601")
        income_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME, code="707")
        journal = AccJournalFactory(
            tenant=tenant,
            type=AccJournal.TYPE_CASH,
            code="CAISSE LIFE",
            default_account=cash_account,
        )
        fiscal_year = AccFiscalYearFactory(
            tenant=tenant, date_start=dt.date(2025, 1, 1), date_end=dt.date(2025, 12, 31)
        )
        AccPeriodFactory(
            tenant=tenant,
            fiscal_year=fiscal_year,
            date_start=dt.date(2025, 1, 1),
            date_end=dt.date(2025, 1, 31),
        )
        AccCashCategoryMappingFactory(
            tenant=tenant, category_label="Achat divers", account=expense_account
        )
    return {
        "tenant": tenant,
        "cash_account": cash_account,
        "expense_account": expense_account,
        "income_account": income_account,
        "journal": journal,
    }


def test_clean_row_creates_a_balanced_draft_move(cash_setup) -> None:
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE LIFE",
                "Achat divers",
                "Non",
                None,
                "Achat fournitures",
                0,
                15000,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes, filename="journal.xlsx")

        assert summary.ok_count == 1
        assert summary.anomaly_count == 0

        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_OK
        assert row.move is not None
        assert row.move.state == AccMove.STATE_DRAFT
        # `total_debit`/`total_credit` ne sont calcules qu'a la publication
        # (`post_move`, jamais appele ici — l'ecriture reste volontairement
        # en brouillon) : l'equilibre se verifie donc directement sur les
        # lignes, pas sur ces champs denormalises encore a zero.
        lines = list(row.move.lines.all())
        assert (
            sum(line.debit for line in lines)
            == sum(line.credit for line in lines)
            == Decimal("15000.0000")
        )
        assert {line.account_id for line in lines} == {
            cash_setup["cash_account"].id,
            cash_setup["expense_account"].id,
        }


def test_both_entree_and_sortie_is_a_real_anomaly(cash_setup) -> None:
    """Cas reel confirme sur le fichier de reference fourni par
    l'utilisateur : exactement 1 ligne sur 3447 avait entree ET sortie
    renseignees simultanement."""
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE LIFE",
                "Achat divers",
                "Non",
                None,
                "Anomalie",
                5000,
                15000,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)

        assert summary.anomaly_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_ANOMALY
        assert ANOMALY_MONTANT_ENTREE_ET_SORTIE in row.anomaly_codes
        assert row.move is None


def test_zero_amount_row_is_an_anomaly_unless_excluded(cash_setup) -> None:
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE LIFE",
                "Achat divers",
                "Non",
                None,
                "Ligne vide",
                0,
                0,
            ],
            [
                dt.datetime(2025, 1, 15),
                "CAISSE LIFE",
                "Report à nouveau",
                "Oui",
                None,
                "SOLDE CAISSE",
                0,
                0,
            ],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)

        assert summary.anomaly_count == 1
        assert summary.ok_count == 1
        anomaly_row, excluded_row = AccImportRow.objects.filter(batch=summary.batch).order_by(
            "row_number"
        )
        assert ANOMALY_MONTANT_NUL in anomaly_row.anomaly_codes
        assert excluded_row.status == AccImportRow.STATUS_OK
        assert excluded_row.move is None  # ligne de solde de periode, jamais une vraie ecriture


def test_unmapped_category_without_explicit_account_is_an_anomaly(cash_setup) -> None:
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE LIFE",
                "Categorie jamais vue",
                "Non",
                None,
                "Achat",
                0,
                5000,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)

        assert summary.anomaly_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert ANOMALY_CATEGORIE_NON_MAPPEE in row.anomaly_codes


def test_aberrant_date_is_an_anomaly() -> None:
    """Cas reel documente par l'utilisateur lui-meme dans son fichier :
    9 lignes avaient une annee aberrante (3035, 2015, 1990)."""
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(3035, 1, 15),
                "CAISSE LIFE",
                "Achat divers",
                "Non",
                None,
                "Date aberrante",
                0,
                5000,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)

        assert summary.anomaly_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert ANOMALY_DATE_INVALIDE in row.anomaly_codes


def test_resolve_import_row_creates_move_once_account_is_assigned(cash_setup) -> None:
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE LIFE",
                "Categorie jamais vue",
                "Non",
                None,
                "Achat",
                0,
                5000,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_ANOMALY

        resolved = resolve_import_row(row, account=cash_setup["expense_account"])

        assert resolved.status == AccImportRow.STATUS_RESOLVED
        assert resolved.move is not None
        assert resolved.move.state == AccMove.STATE_DRAFT


def test_resolve_import_row_can_discard_a_row(cash_setup) -> None:
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [[dt.datetime(2025, 1, 15), "CAISSE LIFE", "Inconnue", "Non", None, "Doublon", 0, 5000]]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)
        row = AccImportRow.objects.get(batch=summary.batch)

        resolved = resolve_import_row(row, discard=True)

        assert resolved.status == AccImportRow.STATUS_DISCARDED
        assert resolved.move is None


def test_unknown_cash_journal_is_an_anomaly() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE INEXISTANTE",
                "Achat divers",
                "Non",
                None,
                "Achat",
                0,
                5000,
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)

        assert summary.anomaly_count == 1


def test_import_accepts_canonical_header_aliases(cash_setup) -> None:
    """Le libelle canonique "COMPTE PCG" doit fonctionner a l'identique du
    libelle reel "CODE PCG DETECTE" utilise dans les autres tests de ce
    fichier — mecanisme de compatibilite ascendante par alias."""
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [[dt.datetime(2025, 1, 15), "CAISSE LIFE", "", "Non", "601", "Achat", 0, 15000]],
        header=[
            "DATE",
            "CAISSE",
            "CATEGORIE",
            "EXCLU DES TOTAUX",
            "COMPTE PCG",
            "LIBELLE",
            "ENTREE",
            "SORTIE",
        ],
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes)

        assert summary.ok_count == 1


def test_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [[dt.datetime(2025, 1, 15), "CAISSE LIFE", "Achat", "Non", None, "X", 0, 100]]
    )

    with use_tenant(tenant.id), pytest.raises(ValueError, match="non supporté"):
        import_cash_journal_xlsx(tenant, file_bytes, format_version=CASH_JOURNAL_FORMAT_VERSION + 1)
