"""Rapports de base de la phase 1 (ACC-BAL, ACC-GL, ACC-JRN, ACC-FAC) —
les rapports financiers complets (bilan, compte de resultat, flux de
tresorerie, variation des capitaux propres, declaration TVA, balances
agees, analytique) sont reportes a la phase 2 du module (cf. plan)."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccMoveLine


def rows_to_bytes(rows: list[dict[str, Any]], fields: list[str], *, format: str = "json") -> bytes:
    if format == "json":
        import json

        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(field) for field in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format de rapport non supporte : {format}")


def trial_balance(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-BAL — balance generale : pour chaque compte mouvemente, total
    debit/credit et solde, toutes ecritures publiees de l'exercice."""
    lines = AccMoveLine.objects.filter(
        move__period__fiscal_year=fiscal_year, move__state=AccMove.STATE_POSTED
    )
    totals = (
        lines.values("account__code", "account__name")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        .order_by("account__code")
    )
    rows = []
    for entry in totals:
        debit = entry["total_debit"] or Decimal(0)
        credit = entry["total_credit"] or Decimal(0)
        rows.append(
            {
                "code": entry["account__code"],
                "name": entry["account__name"],
                "debit": debit,
                "credit": credit,
                "balance": debit - credit,
            }
        )
    return rows


def general_ledger(account: AccAccount, fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-GL — grand livre d'un compte : le detail des lignes publiees,
    par ordre chronologique."""
    lines = (
        AccMoveLine.objects.filter(
            account=account,
            move__period__fiscal_year=fiscal_year,
            move__state=AccMove.STATE_POSTED,
        )
        .select_related("move")
        .order_by("move__date", "move__reference")
    )
    return [
        {
            "date": line.move.date,
            "reference": line.move.reference,
            "label": line.label,
            "debit": line.debit,
            "credit": line.credit,
        }
        for line in lines
    ]


def journal_report(journal: AccJournal, fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-JRN — journal : toutes les ecritures publiees d'un journal,
    dans l'ordre de leur numerotation."""
    moves = AccMove.objects.filter(
        journal=journal, period__fiscal_year=fiscal_year, state=AccMove.STATE_POSTED
    ).order_by("reference")
    rows = []
    for move in moves:
        for line in move.lines.all():
            rows.append(
                {
                    "reference": move.reference,
                    "date": move.date,
                    "account": line.account.code,
                    "label": line.label,
                    "debit": line.debit,
                    "credit": line.credit,
                }
            )
    return rows


def invoice_pdf(invoice: AccMove) -> bytes:
    """ACC-FAC — facture client, document PDF bilingue (FR/EN) minimal."""
    from weasyprint import HTML

    lines_html = "".join(
        f"<tr><td>{line.label}</td><td>{line.debit or line.credit}</td></tr>"
        for line in invoice.lines.all()
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Facture / Invoice {invoice.reference}</h1>
      <p>Date : {invoice.date}</p>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>Libelle / Label</th><th>Montant / Amount</th></tr></thead>
        <tbody>{lines_html}</tbody>
      </table>
      <p>Total : {invoice.total_debit} {invoice.currency}</p>
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result
