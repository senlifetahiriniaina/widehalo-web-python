"""PAY-BULL — bulletin de paie individuel, bilingue, format malgache. PDF
via WeasyPrint (meme patron que `sales.services.reports.quotation_pdf`/
ACC-FAC/`mrp.services.reports.order_pdf`)."""

from __future__ import annotations

from apps.payroll.models import PayPayslip


def payslip_pdf(payslip: PayPayslip) -> bytes:
    from weasyprint import HTML

    lines_html = "".join(
        f"<tr><td>{line.label}</td><td>{line.base}</td><td>{line.rate or ''}</td>"
        f"<td>{line.amount}</td></tr>"
        for line in payslip.lines.all()
        if line.rule is None or line.rule.appears_on_payslip
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Bulletin de paie / Payslip {payslip.reference}</h1>
      <p>Employe / Employee : {payslip.employee_id}</p>
      <p>Periode / Period : {payslip.date_from} - {payslip.date_to}</p>
      <p>Jours travailles / Worked days : {payslip.worked_days}</p>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>Rubrique / Item</th><th>Base</th><th>Taux / Rate</th>
        <th>Montant / Amount</th></tr></thead>
        <tbody>{lines_html}</tbody>
      </table>
      <p>Brut / Gross : {payslip.gross} MGA</p>
      <p>Cotisations salariales / Employee contributions : {payslip.social_employee} MGA</p>
      <p>IRSA : {payslip.irsa} MGA</p>
      <p>Net a payer / Net to pay : {payslip.net_to_pay} MGA</p>
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result
