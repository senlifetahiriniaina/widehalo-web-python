"""Import de factures client/fournisseur depuis un fichier xlsx — jeu de
donnees synthetique (jamais un fichier reel), cf. docs/IMPORT_FORMATS.md
§6. Nouvel importeur du chantier RG-QUALIF, demonstration de bout en bout
du socle de qualification sur un type de donnee sans import prealable."""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from apps.accounting.models import (
    AccAccount,
    AccInvoiceImportRow,
    AccJournal,
    AccMove,
    AccTax,
)
from apps.accounting.services.invoice_import import (
    ANOMALY_PARTENAIRE_NON_IDENTIFIE,
    ANOMALY_PRODUIT_INCONNU,
    ANOMALY_QUANTITE_INVALIDE,
    ANOMALY_REFERENCE_MANQUANTE,
    ANOMALY_TVA_NON_DETERMINEE,
    INVOICE_IMPORT_FORMAT_VERSION,
    decide_qualification,
    ensure_qualification_approval_rule,
    import_invoices_xlsx,
    qualify_import_row,
    resolve_import_row,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccFiscalYearFactory,
    AccJournalFactory,
    AccPeriodFactory,
    AccTaxFactory,
)
from apps.catalog.tests.factories import ProductVariantFactory
from apps.core.models.workflow import ApprovalRequest
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.partners.models import Partner
from apps.partners.tests.factories import PartnerFactory

pytestmark = pytest.mark.django_db

_HEADER = [
    "REFERENCE",
    "DATE",
    "SENS",
    "PARTENAIRE",
    "CODE_PRODUIT",
    "DESIGNATION",
    "QUANTITE",
    "PRIX_UNITAIRE",
    "TAUX_TVA",
    "COMPTE",
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


@pytest.fixture
def invoice_setup():
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        receivable = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE, code="411")
        payable = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE, code="401")
        income = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME, code="707")
        expense = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE, code="607")
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE, code="VTE")
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PURCHASE, code="ACH")
        fiscal_year = AccFiscalYearFactory(
            tenant=tenant, date_start=dt.date(2025, 1, 1), date_end=dt.date(2025, 12, 31)
        )
        AccPeriodFactory(
            tenant=tenant,
            fiscal_year=fiscal_year,
            date_start=dt.date(2025, 1, 1),
            date_end=dt.date(2025, 1, 31),
        )
        variant = ProductVariantFactory(tenant=tenant, reference="PRD001")
        client = PartnerFactory(tenant=tenant, name="Client Test Sarl", roles=[Partner.ROLE_CLIENT])
    return {
        "tenant": tenant,
        "receivable": receivable,
        "payable": payable,
        "income": income,
        "expense": expense,
        "variant": variant,
        "client": client,
    }


def test_fully_identified_customer_invoice_is_ok(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                "FAC-001",
                dt.date(2025, 1, 15),
                "client",
                "Client Test Sarl",
                "PRD001",
                "Vente textile",
                10,
                1000,
                None,
                "",
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes, filename="factures.xlsx")

        assert summary.total_rows == 1
        assert summary.invoices_created_count == 1
        row = AccInvoiceImportRow.objects.get(batch=summary.batch)
        assert row.status == AccInvoiceImportRow.STATUS_NEEDS_QUALIFICATION
        # TVA absente -> toujours needs_qualification (sujet sensible),
        # meme si partenaire/produit sont parfaitement identifies.
        assert row.uses_placeholder_partner is False
        assert row.uses_placeholder_variant is False
        assert row.uses_placeholder_tax is True
        assert row.resolved_variant_id == invoice_setup["variant"].id
        assert row.partner_id == invoice_setup["client"].id
        assert row.move is not None
        assert row.move.move_type == AccMove.TYPE_CUSTOMER_INVOICE
        assert row.move.state == AccMove.STATE_DRAFT


def test_known_tax_rate_resolves_without_placeholder(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    with use_tenant(tenant.id):
        vat_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="4457")
        AccTaxFactory(
            tenant=tenant,
            type=AccTax.TYPE_SALE,
            rate=Decimal("20.000"),
            account_collected=vat_account,
        )
    file_bytes = _build_xlsx(
        [
            [
                "FAC-002",
                dt.date(2025, 1, 15),
                "client",
                "Client Test Sarl",
                "PRD001",
                "Vente textile",
                10,
                1000,
                20,
                "",
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)
        row = AccInvoiceImportRow.objects.get(batch=summary.batch)

        assert row.status == AccInvoiceImportRow.STATUS_OK
        assert row.uses_placeholder_tax is False
        lines = list(row.move.lines.all())
        vat_line = next(line for line in lines if "TVA" in line.label)
        assert vat_line.debit == Decimal("2000.0000") or vat_line.credit == Decimal("2000.0000")


def test_multiline_invoice_groups_by_reference(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    with use_tenant(tenant.id):
        ProductVariantFactory(tenant=tenant, reference="PRD002")
    file_bytes = _build_xlsx(
        [
            [
                "FAC-010",
                dt.date(2025, 1, 15),
                "client",
                "Client Test Sarl",
                "PRD001",
                "Ligne 1",
                5,
                1000,
                None,
                "",
            ],
            [
                "FAC-010",
                dt.date(2025, 1, 15),
                "client",
                "Client Test Sarl",
                "PRD002",
                "Ligne 2",
                2,
                500,
                None,
                "",
            ],
        ]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)

        assert summary.invoices_created_count == 1
        rows = list(AccInvoiceImportRow.objects.filter(batch=summary.batch))
        assert len({row.move_id for row in rows}) == 1
        move = rows[0].move
        assert move.lines.count() >= 3  # client + 2 lignes produit (TVA absente ici)


def test_unresolved_partner_and_product_use_placeholders(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                "FAC-020",
                dt.date(2025, 1, 15),
                "client",
                "Client Totalement Inconnu",
                "REF-INCONNUE",
                "Vente",
                1,
                100,
                None,
                "",
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)
        row = AccInvoiceImportRow.objects.get(batch=summary.batch)

        assert row.status == AccInvoiceImportRow.STATUS_NEEDS_QUALIFICATION
        assert row.uses_placeholder_partner is True
        assert row.uses_placeholder_variant is True
        assert ANOMALY_PARTENAIRE_NON_IDENTIFIE in row.anomaly_codes
        assert ANOMALY_PRODUIT_INCONNU in row.anomaly_codes
        assert ANOMALY_TVA_NON_DETERMINEE in row.anomaly_codes


def test_missing_reference_is_unresolvable(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    file_bytes = _build_xlsx(
        [["", dt.date(2025, 1, 15), "client", "Client Test Sarl", "PRD001", "X", 1, 100, None, ""]]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)

        assert summary.unresolvable_count == 1
        row = AccInvoiceImportRow.objects.get(batch=summary.batch)
        assert row.status == AccInvoiceImportRow.STATUS_UNRESOLVABLE
        assert ANOMALY_REFERENCE_MANQUANTE in row.anomaly_codes
        assert row.move is None


def test_invalid_quantity_is_unresolvable(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                "FAC-030",
                dt.date(2025, 1, 15),
                "client",
                "Client Test Sarl",
                "PRD001",
                "X",
                0,
                100,
                None,
                "",
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)

        assert summary.unresolvable_count == 1
        row = AccInvoiceImportRow.objects.get(batch=summary.batch)
        assert ANOMALY_QUANTITE_INVALIDE in row.anomaly_codes


def test_missing_accounting_configuration_is_unresolvable() -> None:
    """Aucun journal d'achat parametre pour ce tenant -> configuration
    comptable manquante, non-defaultable."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE, code="401")
        fiscal_year = AccFiscalYearFactory(
            tenant=tenant, date_start=dt.date(2025, 1, 1), date_end=dt.date(2025, 12, 31)
        )
        AccPeriodFactory(
            tenant=tenant,
            fiscal_year=fiscal_year,
            date_start=dt.date(2025, 1, 1),
            date_end=dt.date(2025, 1, 31),
        )
    file_bytes = _build_xlsx(
        [
            [
                "FAC-040",
                dt.date(2025, 1, 15),
                "fournisseur",
                "Fournisseur Sarl",
                "REF",
                "X",
                1,
                100,
                None,
                "",
            ]
        ]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)

        assert summary.unresolvable_count == 1


def test_rejects_unknown_future_format_version(invoice_setup) -> None:
    tenant = invoice_setup["tenant"]
    file_bytes = _build_xlsx(
        [["FAC-050", dt.date(2025, 1, 15), "client", "X", "PRD001", "X", 1, 100, None, ""]]
    )

    with use_tenant(tenant.id), pytest.raises(ValueError, match="non supporté"):
        import_invoices_xlsx(tenant, file_bytes, format_version=INVOICE_IMPORT_FORMAT_VERSION + 1)


def test_resolve_import_row_only_supports_discard(invoice_setup) -> None:
    from django.core.exceptions import ValidationError

    tenant = invoice_setup["tenant"]
    file_bytes = _build_xlsx(
        [["", dt.date(2025, 1, 15), "client", "X", "PRD001", "X", 1, 100, None, ""]]
    )

    with use_tenant(tenant.id):
        summary = import_invoices_xlsx(tenant, file_bytes)
        row = AccInvoiceImportRow.objects.get(batch=summary.batch)

        with pytest.raises(ValidationError):
            resolve_import_row(row)

        discarded = resolve_import_row(row, discard=True)
        assert discarded.status == AccInvoiceImportRow.STATUS_DISCARDED


class TestQualifyImportRow:
    def test_qualify_replaces_placeholder_tax_and_creates_an_approval_request(
        self, invoice_setup
    ) -> None:
        tenant = invoice_setup["tenant"]
        with use_tenant(tenant.id):
            vat_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="4457")
            file_bytes = _build_xlsx(
                [
                    [
                        "FAC-060",
                        dt.date(2025, 1, 15),
                        "client",
                        "Client Test Sarl",
                        "PRD001",
                        "Vente",
                        10,
                        1000,
                        None,
                        "",
                    ]
                ]
            )
            summary = import_invoices_xlsx(tenant, file_bytes)
            row = AccInvoiceImportRow.objects.get(batch=summary.batch)
            assert row.status == AccInvoiceImportRow.STATUS_NEEDS_QUALIFICATION
            qualifier = UserFactory()

            qualified = qualify_import_row(row, tax_account=vat_account, qualified_by=qualifier)

            assert qualified.status == AccInvoiceImportRow.STATUS_PENDING_APPROVAL
            assert qualified.uses_placeholder_tax is False
            assert ApprovalRequest.objects.filter(
                id=qualified.qualification_approval_request_id
            ).exists()

    def test_qualify_marks_qualified_directly_when_rule_is_inactive(self, invoice_setup) -> None:
        tenant = invoice_setup["tenant"]
        with use_tenant(tenant.id):
            vat_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="4457")
            file_bytes = _build_xlsx(
                [
                    [
                        "FAC-070",
                        dt.date(2025, 1, 15),
                        "client",
                        "Client Test Sarl",
                        "PRD001",
                        "Vente",
                        10,
                        1000,
                        None,
                        "",
                    ]
                ]
            )
            summary = import_invoices_xlsx(tenant, file_bytes)
            row = AccInvoiceImportRow.objects.get(batch=summary.batch)
            qualifier = UserFactory()

            rule = ensure_qualification_approval_rule(tenant)
            rule.is_active = False
            rule.save(update_fields=["is_active"])

            qualified = qualify_import_row(row, tax_account=vat_account, qualified_by=qualifier)

            assert qualified.status == AccInvoiceImportRow.STATUS_QUALIFIED


class TestDecideQualification:
    def test_approving_marks_the_row_qualified(self, invoice_setup) -> None:
        tenant = invoice_setup["tenant"]
        with use_tenant(tenant.id):
            vat_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="4457")
            file_bytes = _build_xlsx(
                [
                    [
                        "FAC-080",
                        dt.date(2025, 1, 15),
                        "client",
                        "Client Test Sarl",
                        "PRD001",
                        "Vente",
                        10,
                        1000,
                        None,
                        "",
                    ]
                ]
            )
            summary = import_invoices_xlsx(tenant, file_bytes)
            row = AccInvoiceImportRow.objects.get(batch=summary.batch)
            qualifier = UserFactory()
            approver = UserFactory()
            # RG-QUALIF : `ApprovalRule.approver_role="direction"` — un
            # utilisateur sans rôle n'est plus un approbateur éligible
            # depuis le garde-fou `is_eligible_approver` (audit
            # docs/audit/2026-09-cahier-des-charges-v3-audit.md, §9).
            grant_role(approver, "direction")

            qualified = qualify_import_row(row, tax_account=vat_account, qualified_by=qualifier)
            decided = decide_qualification(
                qualified.qualification_approval_request, approver, approved=True
            )

            assert decided.status == AccInvoiceImportRow.STATUS_QUALIFIED
