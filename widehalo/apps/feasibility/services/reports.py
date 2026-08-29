"""Rapport « FEA-STUDY » — document composite (cout/prix/marge par ligne
+ synthese) genere pour une `FeaStudy` donnee.

**Decision de conception** (meme raisonnement que
`apps.strategy.services.business_plan`/`apps.financing.services.reports`) :
ce n'est PAS un rapport tabulaire simple (plusieurs sections : entete
etude, tableau des lignes, synthese cout/marge globale) donc construit
DIRECTEMENT en WeasyPrint (chaine HTML assemblee en Python,
`HTML(string=...).write_pdf()`), plutot que force dans le contrat
`render_rows -> list[dict]` du moteur `reporting`. Neanmoins enregistre
dans le catalogue `reporting` (cf. `services/reports_registration.py`,
`FEA-STUDY`, `render_pdf`-only) pour rester decouvrable/planifiable comme
tout autre rapport."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.feasibility.models import FeaStudy


def _amount(value: Any) -> str:
    if isinstance(value, Decimal):
        return f"{value:,.2f}".replace(",", " ")
    return str(value)


def _line_label(hypothetical_spec: dict[str, Any], variant_id: Any) -> str:
    if hypothetical_spec.get("name"):
        return str(hypothetical_spec["name"])
    if variant_id:
        return f"Variante {variant_id}"
    return "(sans nom)"


def _lines_table(study: FeaStudy) -> str:
    rows_html = []
    for line in study.lines.all():
        cost_total = line.total_cost_mga()
        revenue_total = line.total_revenue_mga()
        rows_html.append(
            "<tr>"
            f"<td>{_line_label(line.hypothetical_spec, line.variant_id)}</td>"
            f"<td>{_amount(line.assumed_qty)}</td>"
            f"<td>{_amount(line.assumed_unit_price_mga)}</td>"
            f"<td>{_amount(cost_total)}</td>"
            f"<td>{_amount(revenue_total)}</td>"
            f"<td>{_amount(line.computed_margin_pct)}%</td>"
            "</tr>"
        )
    return (
        '<table border="1" cellspacing="0" cellpadding="4">'
        "<thead><tr>"
        "<th>Produit</th><th>Qte hypothese</th><th>Prix unitaire (MGA)</th>"
        "<th>Cout total (MGA)</th><th>CA hypothese (MGA)</th><th>Marge %</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def _summary_section(study: FeaStudy) -> str:
    total_cost = study.total_cost_mga()
    total_revenue = study.total_revenue_mga()
    margin_mga = total_revenue - total_cost
    return (
        "<h2>Synthese</h2>"
        f"<p>Cout total simule : {_amount(total_cost)} MGA</p>"
        f"<p>Chiffre d'affaires hypothese : {_amount(total_revenue)} MGA</p>"
        f"<p>Marge hypothese : {_amount(margin_mga)} MGA</p>"
    )


def generate_feasibility_study_pdf(study: FeaStudy) -> bytes:
    """`FEA-STUDY` : document composite (entete + tableau des lignes +
    synthese) pour UNE etude de faisabilite donnee."""
    from weasyprint import HTML

    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Etude de faisabilite — {study.name}</h1>
      <p>Reference : {study.reference}</p>
      <p>Secteur : {study.get_sector_code_display() if study.sector_code else "-"}</p>
      <p>Statut : {study.get_status_display()}</p>
      <p>{study.description}</p>
      <h2>Produits simules</h2>
      {_lines_table(study)}
      {_summary_section(study)}
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result
