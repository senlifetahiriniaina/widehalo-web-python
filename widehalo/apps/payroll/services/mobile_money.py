"""PAY-MM1 (§5.10.11, "Virement de salaire par mobile money", verdict
Adopter) : generateur de fichier de virement mobile money, format simple
DOCUMENTE — **jamais d'integration API reelle avec un operateur** (meme
discipline que la reconciliation mobile money deja construite en A15,
`apps.accounting`, qui reste elle aussi un rapprochement de RELEVE, jamais
un appel API operateur reel)."""

from __future__ import annotations

import csv
import io

from apps.payroll.models import PayBatch, PayPayslip
from apps.payroll.services.regularization import regularization_movement

MOBILE_MONEY_FIELDNAMES = ["employee_id", "reference", "phone", "amount_mga", "label"]


def generate_mobile_money_transfer_file(
    batch: PayBatch, *, phone_by_employee: dict[str, str]
) -> str:
    """CSV texte (format simple documente, PAS un format proprietaire d'un
    operateur reel) : une ligne par bulletin dont `payment_method ==
    "mobile_money"`. `phone_by_employee` : `{str(employee_id): numero}` —
    fourni par l'appelant (aucun module ne porte le numero mobile money
    d'un employe en V1, disclosed)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=MOBILE_MONEY_FIELDNAMES)
    writer.writeheader()
    for payslip in batch.payslips.filter(payment_method=PayPayslip.PAYMENT_MOBILE_MONEY).exclude(
        state=PayPayslip.STATE_CANCELLED
    ):
        writer.writerow(
            {
                "employee_id": str(payslip.employee_id),
                "reference": payslip.reference,
                "phone": phone_by_employee.get(str(payslip.employee_id), ""),
                # L14/PAY-9 : le MOUVEMENT, jamais la valeur pleine. Un
                # rectificatif ordonnait sinon un second virement complet
                # au salarie, alors que seul l'ecart lui est du.
                "amount_mga": str(regularization_movement(payslip, "net_to_pay")),
                "label": f"Salaire {batch.period.code}",
            }
        )
    return buffer.getvalue()


def generate_bank_transfer_file(batch: PayBatch, *, iban_by_employee: dict[str, str]) -> str:
    """Meme format simple pour le fichier de virement bancaire classique
    (PAY-VIR, §5.10.8) — genere en complement (jamais a la place) du
    fichier mobile money, cf. §5.10.11."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["employee_id", "reference", "iban", "amount_mga", "label"]
    )
    writer.writeheader()
    for payslip in batch.payslips.filter(payment_method=PayPayslip.PAYMENT_BANK).exclude(
        state=PayPayslip.STATE_CANCELLED
    ):
        writer.writerow(
            {
                "employee_id": str(payslip.employee_id),
                "reference": payslip.reference,
                "iban": iban_by_employee.get(str(payslip.employee_id), ""),
                # L14/PAY-9 : cf. `generate_mobile_money_file` ci-dessus.
                "amount_mga": str(regularization_movement(payslip, "net_to_pay")),
                "label": f"Salaire {batch.period.code}",
            }
        )
    return buffer.getvalue()
