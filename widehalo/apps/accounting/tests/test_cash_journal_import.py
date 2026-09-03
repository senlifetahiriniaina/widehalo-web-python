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
from django.core.exceptions import ValidationError
from openpyxl import Workbook

from apps.accounting.models import AccAccount, AccImportRow, AccJournal, AccMove
from apps.accounting.services.cash_journal_import import (
    ANOMALY_CATEGORIE_NON_MAPPEE,
    ANOMALY_DATE_INVALIDE,
    ANOMALY_MONTANT_ENTREE_ET_SORTIE,
    ANOMALY_MONTANT_NUL,
    ANOMALY_PERIODE_INDISPONIBLE,
    CASH_JOURNAL_FORMAT_VERSION,
    decide_qualification,
    ensure_qualification_approval_rule,
    import_cash_journal_xlsx,
    qualify_import_row,
    resolve_import_row,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccCashCategoryMappingFactory,
    AccFiscalYearFactory,
    AccJournalFactory,
    AccPeriodFactory,
)
from apps.core.models.workflow import ApprovalRequest
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.partners.models import Partner
from apps.partners.tests.factories import PartnerFactory

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

HEADER_WITH_PARTNER = [*HEADER, "PARTENAIRE", "CLIENT", "FOURNISSEUR"]


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
    """Ligne parfaitement identifiee (compte + partenaire reels, date/
    periode valides) — aucun placeholder, `STATUS_OK` inchange depuis
    avant le chantier RG-QUALIF."""
    tenant = cash_setup["tenant"]
    with use_tenant(tenant.id):
        supplier = PartnerFactory(
            tenant=tenant, name="Fournitures Sarl", roles=[Partner.ROLE_SUPPLIER]
        )
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
                "",
                "",
                "Fournitures Sarl",
            ]
        ],
        header=HEADER_WITH_PARTNER,
    )

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, file_bytes, filename="journal.xlsx")

        assert summary.ok_count == 1
        assert summary.needs_qualification_count == 0
        assert summary.unresolvable_count == 0

        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_OK
        assert row.partner_id == supplier.id
        assert row.uses_placeholder_account is False
        assert row.uses_placeholder_partner is False
        assert row.move is not None
        assert row.move.state == AccMove.STATE_DRAFT
        assert row.move.partner_id == supplier.id
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


def test_row_with_no_partner_name_needs_qualification_via_placeholder(cash_setup) -> None:
    """Nouveau comportement RG-QUALIF : aucun nom de partenaire fourni ->
    placeholder cree, la ligne reste materialisee (move cree) mais passe
    `needs_qualification` plutot que `ok`."""
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

        assert summary.needs_qualification_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_NEEDS_QUALIFICATION
        assert row.uses_placeholder_partner is True
        assert row.partner_id is not None
        assert row.move is not None


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

        assert summary.unresolvable_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_UNRESOLVABLE
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

        assert summary.unresolvable_count == 1
        assert summary.ok_count == 1
        anomaly_row, excluded_row = AccImportRow.objects.filter(batch=summary.batch).order_by(
            "row_number"
        )
        assert ANOMALY_MONTANT_NUL in anomaly_row.anomaly_codes
        assert anomaly_row.status == AccImportRow.STATUS_UNRESOLVABLE
        assert excluded_row.status == AccImportRow.STATUS_OK
        assert excluded_row.move is None  # ligne de solde de periode, jamais une vraie ecriture


def test_unmapped_category_without_explicit_account_needs_qualification(cash_setup) -> None:
    """Depuis RG-QUALIF, une categorie non mappee ne bloque plus la ligne :
    repli sur le compte d'attente, un `AccMove` brouillon est materialise
    immediatement, la ligne passe `needs_qualification`."""
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

        assert summary.needs_qualification_count == 1
        assert summary.unresolvable_count == 0
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_NEEDS_QUALIFICATION
        assert ANOMALY_CATEGORIE_NON_MAPPEE in row.anomaly_codes
        assert row.uses_placeholder_account is True
        assert row.move is not None
        assert row.resolved_account is not None
        assert row.resolved_account.is_placeholder is True


def test_aberrant_date_needs_qualification_when_an_open_period_exists(cash_setup) -> None:
    """Cas reel documente par l'utilisateur lui-meme dans son fichier :
    9 lignes avaient une annee aberrante (3035, 2015, 1990). Depuis
    RG-QUALIF, une date invalide est DEfaultable (repli sur la periode
    ouverte la plus recente) tant qu'une periode ouverte existe pour ce
    tenant — la ligne est materialisee et passe `needs_qualification`."""
    tenant = cash_setup["tenant"]
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

        assert summary.needs_qualification_count == 1
        assert summary.unresolvable_count == 0
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_NEEDS_QUALIFICATION
        assert ANOMALY_DATE_INVALIDE in row.anomaly_codes
        assert row.uses_default_date is True
        assert row.move is not None
        # Repli documente : date de debut de la periode ouverte la plus
        # recente (ici la seule periode ouverte du tenant, janvier 2025).
        assert row.move.date == dt.date(2025, 1, 1)


def test_aberrant_date_is_unresolvable_when_no_open_period_exists_at_all() -> None:
    """Sans repli possible (aucune periode ouverte pour ce tenant), la
    date invalide reste non-defaultable — la ligne reste `unresolvable`."""
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        cash_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_CASH, code="571")
        AccJournalFactory(
            tenant=tenant,
            type=AccJournal.TYPE_CASH,
            code="CAISSE LIFE",
            default_account=cash_account,
        )
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

        assert summary.unresolvable_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_UNRESOLVABLE
        assert ANOMALY_DATE_INVALIDE in row.anomaly_codes
        assert ANOMALY_PERIODE_INDISPONIBLE in row.anomaly_codes


def test_resolve_import_row_creates_move_once_account_and_date_are_assigned(cash_setup) -> None:
    """Seuls les codes non-defaultables restent geres par
    `resolve_import_row` depuis RG-QUALIF — ici une date valide mais hors
    de toute periode ouverte (`PERIODE_FERMEE_OU_INEXISTANTE`)."""
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2027, 6, 15),  # hors de la seule periode ouverte (janvier 2025)
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
        assert row.status == AccImportRow.STATUS_UNRESOLVABLE

        resolved = resolve_import_row(
            row, account=cash_setup["expense_account"], date=dt.date(2025, 1, 15)
        )

        assert resolved.status == AccImportRow.STATUS_RESOLVED
        assert resolved.move is not None
        assert resolved.move.state == AccMove.STATE_DRAFT


def test_resolve_import_row_can_discard_a_row(cash_setup) -> None:
    """Ecarte volontairement une ligne genuinement `unresolvable` (caisse
    inconnue, non-defaultable — cf. docstring de module) — aucun `AccMove`
    n'a jamais ete cree pour elle."""
    tenant = cash_setup["tenant"]
    file_bytes = _build_xlsx(
        [
            [
                dt.datetime(2025, 1, 15),
                "CAISSE INEXISTANTE",
                "Inconnue",
                "Non",
                None,
                "Doublon",
                0,
                5000,
            ]
        ]
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

        assert summary.unresolvable_count == 1


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

        # Compte explicite reconnu (pas de placeholder) mais aucun nom de
        # partenaire dans ce header minimal -> placeholder partenaire,
        # needs_qualification (cf. test_row_with_no_partner_name_needs_
        # qualification_via_placeholder pour le detail de ce comportement).
        assert summary.needs_qualification_count == 1
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.uses_placeholder_account is False
        assert row.uses_placeholder_partner is True


def test_rejects_unknown_future_format_version() -> None:
    tenant = TenantFactory()
    file_bytes = _build_xlsx(
        [[dt.datetime(2025, 1, 15), "CAISSE LIFE", "Achat", "Non", None, "X", 0, 100]]
    )

    with use_tenant(tenant.id), pytest.raises(ValueError, match="non supporté"):
        import_cash_journal_xlsx(tenant, file_bytes, format_version=CASH_JOURNAL_FORMAT_VERSION + 1)


def _import_needs_qualification_row(cash_setup):
    """Helper : importe une ligne qui reste `needs_qualification` (compte
    ET partenaire placeholders) pour les tests de qualification."""
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
    summary = import_cash_journal_xlsx(tenant, file_bytes)
    return AccImportRow.objects.get(batch=summary.batch)


class TestQualifyImportRow:
    def test_qualify_replaces_placeholder_account_and_creates_an_approval_request(
        self, cash_setup
    ) -> None:
        tenant = cash_setup["tenant"]
        with use_tenant(tenant.id):
            row = _import_needs_qualification_row(cash_setup)
            assert row.status == AccImportRow.STATUS_NEEDS_QUALIFICATION
            qualifier = UserFactory()

            qualified = qualify_import_row(
                row, account=cash_setup["expense_account"], qualified_by=qualifier
            )

            assert qualified.status == AccImportRow.STATUS_PENDING_APPROVAL
            assert qualified.uses_placeholder_account is False
            assert qualified.resolved_account_id == cash_setup["expense_account"].id
            assert qualified.qualification_approval_request is not None
            assert ApprovalRequest.objects.filter(
                id=qualified.qualification_approval_request_id
            ).exists()
            line = qualified.move.lines.get(account=cash_setup["expense_account"])
            assert line.account_id == cash_setup["expense_account"].id

    def test_qualify_marks_qualified_directly_when_rule_is_inactive(self, cash_setup) -> None:
        tenant = cash_setup["tenant"]
        with use_tenant(tenant.id):
            row = _import_needs_qualification_row(cash_setup)
            qualifier = UserFactory()

            rule = ensure_qualification_approval_rule(tenant)
            rule.is_active = False
            rule.save(update_fields=["is_active"])

            qualified = qualify_import_row(
                row, account=cash_setup["expense_account"], qualified_by=qualifier
            )

            assert qualified.status == AccImportRow.STATUS_QUALIFIED
            assert qualified.qualification_approval_request is None

    def test_qualify_refuses_a_row_not_in_needs_qualification_status(self, cash_setup) -> None:
        tenant = cash_setup["tenant"]
        with use_tenant(tenant.id):
            row = _import_needs_qualification_row(cash_setup)
            row.status = AccImportRow.STATUS_QUALIFIED
            row.save(update_fields=["status"])
            qualifier = UserFactory()

            with pytest.raises(ValidationError):
                qualify_import_row(
                    row, account=cash_setup["expense_account"], qualified_by=qualifier
                )


class TestDecideQualification:
    def test_approving_marks_the_row_qualified(self, cash_setup) -> None:
        tenant = cash_setup["tenant"]
        with use_tenant(tenant.id):
            row = _import_needs_qualification_row(cash_setup)
            qualifier = UserFactory()
            approver = UserFactory()
            # RG-QUALIF : `ApprovalRule.approver_role="direction"` — un
            # utilisateur sans rôle n'est plus un approbateur éligible
            # depuis le garde-fou `is_eligible_approver` (audit
            # docs/audit/2026-09-cahier-des-charges-v3-audit.md, §9).
            grant_role(approver, "direction")

            qualified = qualify_import_row(
                row, account=cash_setup["expense_account"], qualified_by=qualifier
            )
            assert qualified.status == AccImportRow.STATUS_PENDING_APPROVAL

            decided = decide_qualification(
                qualified.qualification_approval_request, approver, approved=True
            )

            assert decided.status == AccImportRow.STATUS_QUALIFIED

    def test_rejecting_returns_the_row_to_needs_qualification(self, cash_setup) -> None:
        tenant = cash_setup["tenant"]
        with use_tenant(tenant.id):
            row = _import_needs_qualification_row(cash_setup)
            qualifier = UserFactory()
            approver = UserFactory()
            grant_role(approver, "direction")

            qualified = qualify_import_row(
                row, account=cash_setup["expense_account"], qualified_by=qualifier
            )

            decided = decide_qualification(
                qualified.qualification_approval_request, approver, approved=False, comment="non"
            )

            assert decided.status == AccImportRow.STATUS_NEEDS_QUALIFICATION
