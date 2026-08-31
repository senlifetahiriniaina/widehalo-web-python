"""FIN1 — cycle de vie du dossier de demande de financement
(`FinLoanApplication`) et de son plan de financement (`FinFinancingPlanLine`).

Cycle de vie SIMPLE (`draft -> submitted -> accepted/rejected`), pas de
`django-fsm-2` (cf. docstring `models.py::FinLoanApplication`) : les gardes
de transition sont portees directement par ces fonctions de service."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.financing.models import FinFinancingPlanLine, FinLoanApplication


def create_loan_application(
    tenant: Tenant,
    *,
    type: str,  # noqa: A002 — coherent avec le champ CDC `FinLoanApplication.type`
    amount_requested_mga: Decimal,
    duration_months: int,
    purpose: str = "",
    currency: str = "MGA",
    bank_partner_id: Any | None = None,
    bank_name: str = "",
    own_contribution_pct: Decimal = Decimal(30),
) -> FinLoanApplication:
    if amount_requested_mga <= 0:
        raise ValidationError(_("Le montant demande doit être strictement positif."))
    if duration_months <= 0:
        raise ValidationError(_("La durée doit être strictement positive."))

    reference = next_reference(tenant, "FINLOAN", timezone.now().year)
    return FinLoanApplication.objects.create(
        tenant=tenant,
        reference=reference,
        type=type,
        amount_requested_mga=amount_requested_mga,
        duration_months=duration_months,
        purpose=purpose,
        currency=currency,
        bank_partner_id=bank_partner_id,
        bank_name=bank_name,
        own_contribution_pct=own_contribution_pct,
    )


def add_financing_plan_line(
    application: FinLoanApplication, *, source: str, amount_mga: Decimal, label: str = ""
) -> FinFinancingPlanLine:
    """Refuse d'ajouter une ligne a un dossier deja soumis — coherent avec
    la discipline generale du projet (`PurRequisition.submit`, `AccBudget`
    approuve...) : une revision d'un dossier deja soumis passe par un
    NOUVEAU dossier, jamais une modification retroactive silencieuse."""
    if application.state != FinLoanApplication.STATE_DRAFT:
        raise ValidationError(
            _("Impossible de modifier le plan de financement d'un dossier déjà soumis.")
        )
    if amount_mga <= 0:
        raise ValidationError(_("Le montant de la ligne doit être strictement positif."))
    return FinFinancingPlanLine.objects.create(
        tenant=application.tenant,
        loan_application=application,
        source=source,
        label=label,
        amount_mga=amount_mga,
    )


def financing_plan_total(application: FinLoanApplication) -> Decimal:
    total = Decimal(0)
    for line in application.financing_plan_lines.all():
        total += line.amount_mga
    return total


def validate_financing_plan_balance(application: FinLoanApplication) -> bool:
    """Verifie que le plan de financement equilibre bien le montant demande
    + l'apport propre implicite (`own_contribution_pct`) — UNIQUEMENT une
    aide au diagnostic (jamais un blocage a la soumission, cf. docstring
    `models.py`) : la fonction indique si le total des lignes couvre au
    moins le montant sollicite, tolerance de 1 Ar pour l'arrondi decimal."""
    total = financing_plan_total(application)
    return total >= application.amount_requested_mga - Decimal("1")


@transaction.atomic
def submit_application(
    application: FinLoanApplication, *, submission_date: dt.date | None = None
) -> None:
    if application.state != FinLoanApplication.STATE_DRAFT:
        raise ValidationError(_("Seul un dossier en brouillon peut être soumis."))
    application.state = FinLoanApplication.STATE_SUBMITTED
    application.submission_date = submission_date or timezone.now().date()
    application.save(update_fields=["state", "submission_date"])


@transaction.atomic
def decide_application(
    application: FinLoanApplication,
    *,
    accepted: bool,
    decision_date: dt.date | None = None,
    rejection_reason: str = "",
) -> None:
    if application.state != FinLoanApplication.STATE_SUBMITTED:
        raise ValidationError(_("Seul un dossier soumis peut recevoir une décision."))
    application.state = (
        FinLoanApplication.STATE_ACCEPTED if accepted else FinLoanApplication.STATE_REJECTED
    )
    application.decision_date = decision_date or timezone.now().date()
    if not accepted:
        application.rejection_reason = rejection_reason
    application.save(update_fields=["state", "decision_date", "rejection_reason"])
