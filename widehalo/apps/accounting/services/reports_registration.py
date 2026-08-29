"""§5.11 reporting : enregistrement des rapports `accounting` dans le
registre partage `core.services.reports_registry`, appele depuis
`apps.py::ready()`. REP4 a enregistre ACC-FAC (RPT-10, archivage legal) ;
REP5 ajoute les rapports tabulaires deja construits par ce module — tous
appellent la fonction deja existante de `services/reports.py`, aucune
reimplementation.

**Portee assumee et disclosed (REP5)** : `balance_sheet`/`cash_flow_
statement`/`financial_ratios`/`fixed_asset_annexes`/`cash_basis_report`/
`dcom_report`/`treasury_forecast` ne sont PAS enregistres ici — ces
fonctions renvoient soit une structure imbriquee non tabulaire (dict de
sections, incompatible avec le contrat `render_rows -> list[dict]` du
registre), soit prennent un objet de declaration specifique en parametre
(`AccDcomDeclaration`) qui demanderait un adaptateur dedie sans valeur
ajoutee immediate. Ces rapports restent pleinement fonctionnels via leurs
endpoints API JSON existants (`/accounting/reports/...`), simplement hors
du catalogue central pour ce chantier — a completer dans un futur
durcissement si le catalogue doit devenir exhaustif."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_invoice_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.accounting.models import AccMove
    from apps.accounting.services.reports import invoice_pdf
    from apps.reporting.services.public import render_and_archive

    invoice = AccMove.objects.get(id=params["object_id"])
    return render_and_archive(
        content_object=invoice, actor=actor, generate_fn=lambda: invoice_pdf(invoice)
    )


def _adapter_trial_balance(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.models import AccFiscalYear
    from apps.accounting.services.reports import trial_balance

    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    return trial_balance(fiscal_year)


def _adapter_general_ledger(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.models import AccAccount, AccFiscalYear
    from apps.accounting.services.reports import general_ledger

    account = AccAccount.objects.get(id=params["account_id"])
    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    return general_ledger(account, fiscal_year)


def _adapter_journal_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.models import AccFiscalYear, AccJournal
    from apps.accounting.services.reports import journal_report

    journal = AccJournal.objects.get(id=params["journal_id"])
    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    return journal_report(journal, fiscal_year)


def _adapter_income_statement(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.models import AccFiscalYear
    from apps.accounting.services.reports import income_statement

    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    return income_statement(fiscal_year)


def _adapter_income_statement_by_function(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.accounting.models import AccFiscalYear
    from apps.accounting.services.reports import income_statement_by_function

    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    return income_statement_by_function(fiscal_year)


def _adapter_equity_variation(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.models import AccFiscalYear
    from apps.accounting.services.reports import equity_variation_statement

    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    return equity_variation_statement(fiscal_year)


def _adapter_aged_receivables(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.services.reports import aged_receivables

    return aged_receivables(params.get("as_of_date"))


def _adapter_aged_payables(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.accounting.services.reports import aged_payables

    return aged_payables(params.get("as_of_date"))


def _adapter_analytical_income_statement(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.accounting.models import AccAnalyticPlan, AccFiscalYear
    from apps.accounting.services.reports import analytical_income_statement

    fiscal_year = AccFiscalYear.objects.get(id=params["fiscal_year_id"])
    analytic_plan = AccAnalyticPlan.objects.get(id=params["analytic_plan_id"])
    return analytical_income_statement(fiscal_year, analytic_plan)


def register_reports() -> None:
    register_report(
        code="ACC-FAC",
        module="accounting",
        label="Facture",
        permission="accounting.view_accmove",
        render_pdf=_adapter_invoice_pdf,
        is_legal_document=True,
    )
    register_report(
        code="ACC-BAL",
        module="accounting",
        label="Balance generale",
        permission="accounting.view_accaccount",
        render_rows=_adapter_trial_balance,
        fields=("code", "name", "debit", "credit", "balance"),
    )
    register_report(
        code="ACC-GL",
        module="accounting",
        label="Grand livre",
        permission="accounting.view_accmove",
        render_rows=_adapter_general_ledger,
        fields=("date", "reference", "label", "debit", "credit"),
    )
    register_report(
        code="ACC-JNL",
        module="accounting",
        label="Journal",
        permission="accounting.view_accmove",
        render_rows=_adapter_journal_report,
        fields=("reference", "date", "account", "label", "debit", "credit"),
    )
    register_report(
        code="ACC-CR",
        module="accounting",
        label="Compte de resultat par nature",
        permission="accounting.view_accaccount",
        render_rows=_adapter_income_statement,
        fields=("poste", "label", "amount"),
    )
    register_report(
        code="ACC-CR-FCT",
        module="accounting",
        label="Compte de resultat par fonction",
        permission="accounting.view_accaccount",
        render_rows=_adapter_income_statement_by_function,
        fields=("label", "amount"),
    )
    register_report(
        code="ACC-VCP",
        module="accounting",
        label="Variation des capitaux propres",
        permission="accounting.view_accaccount",
        render_rows=_adapter_equity_variation,
        fields=("code", "name", "opening", "movement", "closing"),
    )
    register_report(
        code="ACC-AGE-C",
        module="accounting",
        label="Balance agee clients",
        permission="accounting.view_accmove",
        render_rows=_adapter_aged_receivables,
        fields=("partner_id", "moins_d_un_an", "un_a_cinq_ans", "plus_de_cinq_ans", "total"),
    )
    register_report(
        code="ACC-AGE-F",
        module="accounting",
        label="Balance agee fournisseurs",
        permission="accounting.view_accmove",
        render_rows=_adapter_aged_payables,
        fields=("partner_id", "moins_d_un_an", "un_a_cinq_ans", "plus_de_cinq_ans", "total"),
    )
    register_report(
        code="ACC-ANA",
        module="accounting",
        label="Compte de resultat analytique",
        permission="accounting.view_accmove",
        render_rows=_adapter_analytical_income_statement,
        fields=("analytic_account_id", "code", "name", "produits", "charges", "net"),
    )
