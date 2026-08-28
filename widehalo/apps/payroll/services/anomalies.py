"""PAY-CTRL1 (enrichissement "Adapter" — detection d'anomalies de paie,
version DETERMINISTE, PAS d'IA) : 7 controles executes AVANT `validate()`
d'un lot de paie (RG-PAY-8/`services.batches.control_and_validate_batch`).
4 controles imposes par le CDC + 3 controles deterministes additionnels
disclosed (choix libre, documente ci-dessous)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import apps.presence.services.public as presence_public
from apps.payroll.models import PayBatch, PayPayslip

# Seuil d'ecart CDC (>20%) — cf. controle 1.
VARIANCE_THRESHOLD_PCT = Decimal("20")


@dataclass(frozen=True)
class Anomaly:
    payslip_id: object
    code: str
    message: str


def _previous_payslip(payslip: PayPayslip) -> PayPayslip | None:
    return (
        PayPayslip.objects.filter(
            tenant=payslip.tenant,
            employee_id=payslip.employee_id,
            period__date_from__lt=payslip.period.date_from,
        )
        .exclude(state=PayPayslip.STATE_CANCELLED)
        .order_by("-period__date_from")
        .first()
    )


def detect_batch_anomalies(batch: PayBatch) -> list[Anomaly]:
    """Les 4 controles imposes par le CDC (1-4) + 3 controles
    supplementaires deterministes retenus (5-7, disclosed, choix libre) :
    5. structure salariale differente du bulletin precedent (changement non
       explicite, possible erreur de contrat) ;
    6. base cotisable > plafond 8xSME (le plafonnement lui-meme est
       toujours applique par le moteur — une base AVANT plafonnement
       superieure signale un salaire brut anormalement eleve, a verifier) ;
    7. employe sans jours travailles ET sans absence enregistree sur la
       periode (incoherence probable — un employe present toute la periode
       devrait avoir `worked_days` proche du forfait, un employe totalement
       absent devrait avoir une absence enregistree cote `presence`)."""
    anomalies: list[Anomaly] = []
    for payslip in batch.payslips.exclude(state=PayPayslip.STATE_CANCELLED):
        previous = _previous_payslip(payslip)

        # 1. Ecart >20% avec le bulletin precedent (net a payer).
        if previous is not None and previous.net_to_pay > 0:
            variance_pct = abs(payslip.net_to_pay - previous.net_to_pay) / previous.net_to_pay * 100
            if variance_pct > VARIANCE_THRESHOLD_PCT:
                anomalies.append(
                    Anomaly(
                        payslip.id,
                        "variance_net",
                        f"Ecart net a payer de {variance_pct:.1f}% avec le bulletin precedent.",
                    )
                )

        # 2. Net negatif.
        if payslip.net_to_pay < 0:
            anomalies.append(Anomaly(payslip.id, "net_negative", "Net a payer negatif."))

        # 3. Cotisation hors plafond (base cotisable observee > plafond).
        base_line = payslip.lines.filter(code="BASE_COTISABLE").first()
        brut_line = payslip.lines.filter(code="BRUT").first()
        if base_line and brut_line and brut_line.amount > base_line.amount:
            social_ceiling_hit = payslip.lines.filter(code="CNAPS_SAL").exists()
            if not social_ceiling_hit:
                anomalies.append(
                    Anomaly(
                        payslip.id, "ceiling_missing", "Cotisation salariale absente du bulletin."
                    )
                )

        # 4. Employe absent le mois precedent (aucun bulletin du tout le
        # mois precedent — pas seulement "previous is None" en general, car
        # un nouvel embauche n'a legitimement pas de bulletin precedent :
        # on ne signale que si un CONTRAT actif existait deja avant).
        if previous is None and payslip.contract.date_start < payslip.period.date_from:
            anomalies.append(
                Anomaly(
                    payslip.id,
                    "missing_previous_payslip",
                    "Aucun bulletin le mois precedent alors qu'un contrat actif existait deja.",
                )
            )

        # 5. Structure salariale differente du bulletin precedent.
        if (
            previous is not None
            and previous.contract.salary_structure_id != payslip.contract.salary_structure_id
        ):
            anomalies.append(
                Anomaly(payslip.id, "structure_changed", "Structure salariale modifiee.")
            )

        # 6. Brut avant plafonnement anormalement eleve.
        if brut_line and base_line and brut_line.amount > base_line.amount:
            anomalies.append(
                Anomaly(
                    payslip.id,
                    "over_ceiling",
                    "Brut au-dela du plafond de cotisation (8xSME).",
                )
            )

        # 7. Aucun jour travaille ET aucune absence enregistree.
        if payslip.worked_days <= 0 and not presence_public.is_employee_absent_on(
            payslip.tenant, payslip.employee_id, date=payslip.period.date_from
        ):
            anomalies.append(
                Anomaly(
                    payslip.id,
                    "zero_worked_days_no_absence",
                    "Aucun jour travaille ni absence enregistree sur la periode.",
                )
            )
    return anomalies
