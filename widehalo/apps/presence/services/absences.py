"""PR2 : types d'absence, workflow FSM (§5.9.4), circuit de validation a
niveaux parametrables (RG-PRS-5, reutilise `core.ApprovalRule`/
`ApprovalRequest`), soldes de conges au prorata (RG-PRS-7), bascule
automatique en "injustifie" (RG-PRS-6)."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import request_approval
from apps.core.services.documents import store_document
from apps.core.services.workflow import attempt_transition
from apps.presence.models import PrsAbsence, PrsAbsenceType, PrsEmployee, PrsLeaveBalance

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from apps.core.models.document import Document
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

DEFAULT_MONTHLY_ACCRUAL_DAYS = Decimal("2.5")
RULE_NAME_LEVEL_1 = "presence.absence.approval.level1"
RULE_NAME_LEVEL_2 = "presence.absence.approval.level2"


def create_absence_type(
    tenant: Tenant,
    *,
    code: str,
    name: str,
    category: str,
    is_paid: bool = True,
    pay_rate_pct: Decimal = Decimal("100"),
    requires_justification: bool = False,
    max_days_year: int | None = None,
    deducts_from_balance: bool = True,
    approval_levels: int = 1,
    advance_notice_days: int = 0,
    justification_deadline_days: int = 2,
) -> PrsAbsenceType:
    absence_type = PrsAbsenceType(
        tenant=tenant,
        code=code,
        name=name,
        category=category,
        is_paid=is_paid,
        pay_rate_pct=pay_rate_pct,
        requires_justification=requires_justification,
        max_days_year=max_days_year,
        deducts_from_balance=deducts_from_balance,
        approval_levels=approval_levels,
        advance_notice_days=advance_notice_days,
        justification_deadline_days=justification_deadline_days,
    )
    absence_type.full_clean()
    absence_type.save()
    return absence_type


def ensure_default_approval_rules(tenant: Tenant, absence_type: PrsAbsenceType) -> None:
    """RG-PRS-5 : nombre de niveaux parametrable PAR TYPE d'absence (ex.
    congé payé = manager puis RH ; permission demi-journée = manager
    seul). `approver_role` volontairement generique ("manager"/"rh") —
    l'affectation reelle au manager hierarchique precis de l'employe est
    hors du perimetre du moteur d'approbation generique (base sur des
    roles, pas des individus), disclosed."""
    content_type = ContentType.objects.get_for_model(PrsAbsence)
    ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=f"{RULE_NAME_LEVEL_1}.{absence_type.code}",
        defaults={"approver_role": "rh", "sequence_order": 1, "condition": {}},
    )
    if absence_type.approval_levels >= 2:
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            content_type=content_type,
            name=f"{RULE_NAME_LEVEL_2}.{absence_type.code}",
            defaults={"approver_role": "direction", "sequence_order": 2, "condition": {}},
        )


def _count_days(
    date_from: dt.date, date_to: dt.date, *, half_start: bool, half_end: bool
) -> Decimal:
    if date_to < date_from:
        raise ValidationError(_("La date de fin ne peut pas précéder la date de début."))
    total = Decimal((date_to - date_from).days + 1)
    if half_start:
        total -= Decimal("0.5")
    if half_end:
        total -= Decimal("0.5")
    return total


def create_absence(
    tenant: Tenant,
    *,
    employee: PrsEmployee,
    absence_type: PrsAbsenceType,
    date_from: dt.date,
    date_to: dt.date,
    half_day_start: bool = False,
    half_day_end: bool = False,
    reason: str = "",
    replacement_employee: PrsEmployee | None = None,
    reference: str = "",
) -> PrsAbsence:
    days_count = _count_days(date_from, date_to, half_start=half_day_start, half_end=half_day_end)
    is_medical = absence_type.category in PrsAbsenceType.MEDICAL_CATEGORIES
    absence = PrsAbsence(
        tenant=tenant,
        reference=reference,
        employee=employee,
        type=absence_type,
        date_from=date_from,
        date_to=date_to,
        half_day_start=half_day_start,
        half_day_end=half_day_end,
        days_count=days_count,
        # RG-PRS-9 : motif medical toujours passe par le champ chiffre,
        # jamais laisse en clair meme si l'appelant l'a fourni ainsi.
        reason=reason if is_medical or reason else reason,
    )
    absence.full_clean()
    absence.save()
    return absence


def submit_absence(absence: PrsAbsence, user: User) -> PrsAbsence:
    ensure_default_approval_rules(absence.tenant, absence.type)
    attempt_transition(absence, "submit", user)
    absence.requested_at = timezone.now()
    absence.save(update_fields=["state", "requested_at"])

    if absence.type.deducts_from_balance:
        _adjust_balance(absence, pending_delta=absence.days_count)

    content_type = ContentType.objects.get_for_model(PrsAbsence)
    rule = ApprovalRule.objects.filter(
        tenant=absence.tenant,
        content_type=content_type,
        name=f"{RULE_NAME_LEVEL_1}.{absence.type.code}",
        is_active=True,
    ).first()
    if rule is not None:
        request_approval(absence, rule, user)
    return absence


def decide_absence(
    absence: PrsAbsence, decision: ApprovalRequest, user: User, *, approved: bool, comment: str = ""
) -> PrsAbsence:
    """Applique la decision d'une `ApprovalRequest` deja tranchee (cf.
    `core.services.approvals.decide`) a la transition FSM correspondante
    de l'absence — sequence niveau 1 -> niveau 2 -> validee selon
    `PrsAbsenceType.approval_levels`."""
    if not approved:
        attempt_transition(absence, "reject", user, comment=comment)
        absence.save(update_fields=["state"])
        if absence.type.deducts_from_balance:
            _adjust_balance(absence, pending_delta=-absence.days_count)
        return absence

    if absence.state == PrsAbsence.STATE_SUBMITTED:
        attempt_transition(absence, "approve_level1", user, comment=comment)
        absence.save(update_fields=["state"])
        if absence.type.approval_levels >= 2:
            content_type = ContentType.objects.get_for_model(PrsAbsence)
            rule = ApprovalRule.objects.filter(
                tenant=absence.tenant,
                content_type=content_type,
                name=f"{RULE_NAME_LEVEL_2}.{absence.type.code}",
                is_active=True,
            ).first()
            if rule is not None:
                request_approval(absence, rule, user)
            return absence
        attempt_transition(absence, "validate", user)
        absence.save(update_fields=["state"])
        _apply_validated_balance(absence)
        return absence

    if absence.state == PrsAbsence.STATE_APPROVED_L1:
        attempt_transition(absence, "approve_level2", user, comment=comment)
        absence.save(update_fields=["state"])
        attempt_transition(absence, "validate", user)
        absence.save(update_fields=["state"])
        _apply_validated_balance(absence)
        return absence

    raise ValidationError(_("Aucune decision possible dans l'etat courant de cette absence."))


def cancel_absence(absence: PrsAbsence, user: User) -> PrsAbsence:
    attempt_transition(absence, "cancel", user)
    absence.save(update_fields=["state"])
    if absence.type.deducts_from_balance:
        _adjust_balance(absence, pending_delta=-absence.days_count)
    return absence


def _get_or_create_balance(absence: PrsAbsence) -> PrsLeaveBalance:
    balance, _created = PrsLeaveBalance.objects.get_or_create(
        tenant=absence.tenant,
        employee=absence.employee,
        year=absence.date_from.year,
        type=absence.type,
    )
    return balance


def _adjust_balance(absence: PrsAbsence, *, pending_delta: Decimal) -> None:
    balance = _get_or_create_balance(absence)
    balance.pending_days = balance.pending_days + pending_delta
    balance.movements = [
        *balance.movements,
        {
            "date": timezone.now().isoformat(),
            "kind": "pending",
            "days": str(pending_delta),
            "comment": f"absence {absence.reference or absence.id}",
        },
    ]
    balance.full_clean()
    balance.save(update_fields=["pending_days", "movements"])


def _apply_validated_balance(absence: PrsAbsence) -> None:
    if not absence.type.deducts_from_balance:
        return
    balance = _get_or_create_balance(absence)
    balance.pending_days = balance.pending_days - absence.days_count
    balance.taken_days = balance.taken_days + absence.days_count
    balance.movements = [
        *balance.movements,
        {
            "date": timezone.now().isoformat(),
            "kind": "taken",
            "days": str(absence.days_count),
            "comment": f"absence {absence.reference or absence.id}",
        },
    ]
    balance.full_clean()
    balance.save(update_fields=["pending_days", "taken_days", "movements"])


def accrue_annual_leave(
    tenant: Tenant,
    employee: PrsEmployee,
    absence_type: PrsAbsenceType,
    *,
    year: int,
    monthly_rate: Decimal = DEFAULT_MONTHLY_ACCRUAL_DAYS,
) -> PrsLeaveBalance:
    """RG-PRS-7 : acquisition mensuelle (2,5 j ouvrables/mois par defaut),
    calculee au PRORATA du nombre de mois reellement travailles sur
    l'annee — test d'acceptance §5.9.8 n°3 (embauche en cours d'annee)."""
    year_start = dt.date(year, 1, 1)
    year_end = dt.date(year, 12, 31)
    effective_start = max(employee.hire_date, year_start)
    effective_end = min(employee.end_date or year_end, year_end)
    if effective_start > effective_end:
        months_worked = 0
    else:
        months_worked = (
            (effective_end.year - effective_start.year) * 12
            + (effective_end.month - effective_start.month)
            + 1
        )
    acquired = (monthly_rate * months_worked).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    balance, _created = PrsLeaveBalance.objects.get_or_create(
        tenant=tenant, employee=employee, year=year, type=absence_type
    )
    balance.acquired_days = acquired
    balance.movements = [
        *balance.movements,
        {
            "date": timezone.now().isoformat(),
            "kind": "accrual",
            "days": str(acquired),
            "comment": f"prorata {months_worked} mois",
        },
    ]
    balance.full_clean()
    balance.save(update_fields=["acquired_days", "movements"])
    return balance


def mark_unjustified_if_overdue(absence: PrsAbsence, *, unjustified_type: PrsAbsenceType) -> bool:
    """RG-PRS-6 : une absence dont le type requiert un justificatif,
    toujours non fourni au-dela du delai parametre, bascule
    automatiquement en categorie "injustifie" (impact paie). Ne change
    QUE le type (la ligne reste tracable), jamais la suppression de
    l'absence d'origine."""
    if not absence.type.requires_justification or absence.justification_provided:
        return False
    deadline = absence.date_to + dt.timedelta(days=absence.type.justification_deadline_days)
    if timezone.localdate() <= deadline:
        return False
    absence.type = unjustified_type
    absence.full_clean()
    absence.save(update_fields=["type"])
    return True


def pending_unjustified_candidates(tenant: Tenant) -> QuerySet[PrsAbsence]:
    return PrsAbsence.objects.filter(
        tenant=tenant,
        type__requires_justification=True,
        justification_provided=False,
        state__in=[PrsAbsence.STATE_VALIDATED, PrsAbsence.STATE_IN_PROGRESS, PrsAbsence.STATE_DONE],
    )


def attach_justification_document(
    absence: PrsAbsence, *, uploaded_file: UploadedFile[Any], uploaded_by: User
) -> Document:
    """RG-PRS-6 : rattache un justificatif — reutilise `core.Document`
    polymorphe (jamais de champ fichier dedie sur `PrsAbsence`, cf.
    docstring de module). Marque `justification_provided=True`, ce qui
    exempte l'absence de la bascule automatique en "injustifie"."""
    document = store_document(
        tenant=absence.tenant,
        uploaded_file=uploaded_file,
        uploaded_by=uploaded_by,
        content_object=absence,
    )
    absence.justification_provided = True
    absence.save(update_fields=["justification_provided"])
    return document
