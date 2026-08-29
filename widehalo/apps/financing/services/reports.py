"""FIN4 — rapports composites `financing` : FIN-DOSSIER (dossier bancaire
complet, agnostique de la banque destinataire) et FIN-CREDOC (demande
d'ouverture de credit documentaire formatee). Meme patron que les autres
gros documents composites deja construits (`apps.accounting.services.
tax_returns::generate_liasse_is/ir`, `apps.strategy.services.business_plan
::generate_business_plan_pdf`) : chaine HTML assemblee en Python, rendue en
PDF par WeasyPrint — jamais force dans le contrat `render_rows -> list[dict]`
du moteur `reporting` (documents non tabulaires)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.financing.models import FinCredoc, FinForecastScenario, FinLoanApplication
from apps.financing.services.guarantees import check_guarantee_coverage
from apps.financing.services.loan_applications import financing_plan_total

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def _amount(value: Any) -> str:
    if isinstance(value, Decimal):
        return f"{value:,.4f}".replace(",", " ")
    return str(value)


def _rows_table(rows: list[dict[str, Any]], fields: list[str], headers: list[str]) -> str:
    if not rows:
        return "<p>Aucune donnee.</p>"
    thead = "".join(f"<th>{h}</th>" for h in headers)
    tbody_rows = []
    for row in rows:
        cells = "".join(f"<td>{_amount(row.get(f, ''))}</td>" for f in fields)
        tbody_rows.append(f"<tr>{cells}</tr>")
    return (
        '<table border="1" cellspacing="0" cellpadding="4">'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(tbody_rows)}</tbody></table>"
    )


def _dossier_header_section(application: FinLoanApplication) -> str:
    return (
        "<h1>Dossier de financement bancaire</h1>"
        f"<h2>{application.reference} — {application.get_type_display()}</h2>"
        f"<p>Banque : {application.bank_name or 'non renseignee'}</p>"
        f"<p>Montant demande : {_amount(application.amount_requested_mga)} "
        f"{application.currency}</p>"
        f"<p>Duree : {application.duration_months} mois — "
        f"Apport propre : {application.own_contribution_pct}%</p>"
        f"<p>Objet : {application.purpose or 'non precise'}</p>"
        f"<p>Statut : {application.get_state_display()}</p>"
    )


def _financing_plan_section(application: FinLoanApplication) -> str:
    lines = list(application.financing_plan_lines.filter(is_active=True))
    rows = [
        {"source": line.get_source_display(), "label": line.label, "montant": line.amount_mga}
        for line in lines
    ]
    table = _rows_table(rows, ["source", "label", "montant"], ["Source", "Libelle", "Montant"])
    total = financing_plan_total(application)
    return f"<h2>Plan de financement</h2>{table}<p>Total : {_amount(total)}</p>"


def _guarantees_section(application: FinLoanApplication) -> str:
    guarantees = list(application.guarantees.filter(is_active=True))
    rows = [
        {
            "reference": guarantee.reference,
            "type": guarantee.get_type_display(),
            "valeur_estimee": guarantee.estimated_value_mga,
            "statut": guarantee.get_formalization_status_display(),
        }
        for guarantee in guarantees
    ]
    table = _rows_table(
        rows,
        ["reference", "type", "valeur_estimee", "statut"],
        ["Reference", "Type", "Valeur estimee", "Statut de formalisation"],
    )
    coverage = check_guarantee_coverage(application)
    ratio_text = (
        f"{coverage['coverage_ratio']:.2%}" if coverage["coverage_ratio"] is not None else "N/A"
    )
    coverage_text = (
        f"<p>Couverture des suretes (regle >= 120% du credit, cf. plan) : "
        f"{_amount(coverage['total_guarantee_value_mga'])} / "
        f"{_amount(coverage['required_value_mga'])} requis "
        f"({ratio_text}) — {'CONFORME' if coverage['is_covered'] else 'INSUFFISANTE'}.</p>"
    )
    return f"<h2>Suretes</h2>{table}{coverage_text}"


def _forecast_scenario_section(scenario: FinForecastScenario | None) -> str:
    if scenario is None:
        return "<h2>Prevision financiere</h2><p>Aucun scenario de prevision rattache.</p>"
    sections = []
    for statement_type, label in FinForecastScenario.STATEMENT_CHOICES:
        lines = scenario.lines.filter(is_active=True, statement_type=statement_type).order_by(
            "period"
        )
        rows = [
            {"periode": line.period, "libelle": line.label, "montant": line.amount_mga}
            for line in lines
        ]
        table = _rows_table(
            rows, ["periode", "libelle", "montant"], ["Periode", "Libelle", "Montant"]
        )
        sections.append(f"<h3>{label}</h3>{table}")
    return f"<h2>Prevision financiere — {scenario.name}</h2>" + "".join(sections)


def _sales_volume_section(tenant: Tenant, period_from: str, period_to: str) -> str:
    """Section INFORMATIVE (volumes, pas de montant) — cf. docstring
    `models.py::FinForecastScenario` pour la disclosure complete :
    `sales.services.public.get_forecast_summary` renvoie des unites, jamais
    des MGA, et `financing` ne declare pas `catalog` comme dependance pour
    les valoriser."""
    from apps.sales.services.public import get_forecast_summary

    rows = get_forecast_summary(tenant, period_from=period_from, period_to=period_to)
    table = _rows_table(
        [
            {
                "periode": row["period"],
                "variante": row["variant_id"],
                "qte_prevue": row["qty_forecast"],
                "confiance": row["confidence"],
            }
            for row in rows
        ],
        ["periode", "variante", "qte_prevue", "confiance"],
        ["Periode", "Variante", "Qte prevue (unites)", "Confiance"],
    )
    return (
        "<h2>Prevision de ventes (volumes, indicatif)</h2>"
        "<p><em>Section informative en UNITES, pas en montant "
        "(cf. disclosure du code) — n'est pas convertie en chiffre "
        "d'affaires previsionnel dans ce dossier.</em></p>"
        f"{table}"
    )


def _historical_financials_section(tenant: Tenant, fiscal_year_id: Any | None) -> str:
    if fiscal_year_id is None:
        return "<h2>Etats financiers historiques</h2><p>Aucun exercice fourni.</p>"
    from apps.accounting.services.public import get_financial_ratios_summary

    summary = get_financial_ratios_summary(tenant, fiscal_year_id=fiscal_year_id)
    if summary is None:
        return "<h2>Etats financiers historiques</h2><p>Exercice introuvable.</p>"
    ratio1 = summary.get("ratio1", {})
    rows = [{"indicateur": key, "valeur": value} for key, value in ratio1.items()]
    table = _rows_table(rows, ["indicateur", "valeur"], ["Indicateur", "Valeur"])
    return (
        "<h2>Etats financiers historiques (resume ratios, A13)</h2>"
        "<p><em>Resume issu des rapports deja construits par le module "
        "accounting — ne remplace pas la liasse fiscale complete "
        "(ACC-IS/ACC-IR), cf. disclosure du code.</em></p>"
        f"{table}"
    )


def generate_dossier_pdf(
    application: FinLoanApplication,
    *,
    scenario: FinForecastScenario | None = None,
    fiscal_year_id: Any | None = None,
    sales_period_from: str | None = None,
    sales_period_to: str | None = None,
) -> bytes:
    """FIN-DOSSIER : assemblage PDF unique du dossier bancaire complet —
    etats financiers historiques (resume) + prevision + plan de financement
    + garanties. `scenario`/`fiscal_year_id`/`sales_period_*` sont tous
    optionnels (un dossier peut etre genere avant que ces elements ne
    soient renseignes ; les sections correspondantes l'indiquent
    explicitement plutot que d'echouer)."""
    from weasyprint import HTML

    tenant = application.tenant
    sections = (
        _dossier_header_section(application)
        + _historical_financials_section(tenant, fiscal_year_id)
        + _forecast_scenario_section(scenario)
        + (
            _sales_volume_section(tenant, sales_period_from, sales_period_to)
            if sales_period_from and sales_period_to
            else ""
        )
        + _financing_plan_section(application)
        + _guarantees_section(application)
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      {sections}
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result


def generate_credoc_pdf(credoc: FinCredoc) -> bytes:
    """FIN-CREDOC : demande d'ouverture de credit documentaire formatee
    (RUU 600 — reference normative citee par le plan, cf. docstring
    `models.py::FinCredoc` pour la reserve sur la checklist documentaire)."""
    from weasyprint import HTML

    documents = credoc.documents_required or []
    documents_html = (
        "<ul>" + "".join(f"<li>{doc}</li>" for doc in documents) + "</ul>"
        if documents
        else "<p>Aucun document requis renseigne.</p>"
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Demande d'ouverture de credit documentaire (CREDOC)</h1>
      <h2>{credoc.reference}</h2>
      <p>Banque emettrice : {credoc.bank}</p>
      <p>Banque notificatrice : {credoc.advising_bank or "non renseignee"}</p>
      <p>Beneficiaire : {credoc.beneficiary}</p>
      <p>Montant : {_amount(credoc.amount_mga)} {credoc.currency}</p>
      <p>Date de validite : {credoc.validity_date.isoformat()}</p>
      <p>Incoterm : {credoc.incoterm or "non precise"}</p>
      <p>Statut : {credoc.get_state_display()}</p>
      <h3>Documents requis (RUU 600)</h3>
      {documents_html}
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result
