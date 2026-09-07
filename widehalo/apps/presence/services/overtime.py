"""PR2 : heures supplementaires classees par categorie de majoration
(RG-PRS-4).

**Le calendrier a desormais son mot a dire.** Un jour ferie travaille vaut
une majoration de 100 % (multiplicateur 2,00, cf. `payroll.services.seed.
CODE_OVERTIME_MULTIPLIERS`). Declarer des heures du 26 juin en `h_sup_30`
etait accepte sans un mot : la categorie etait un parametre libre, et rien
ne la confrontait aux dates que `core.Holiday` connait pour la societe.

Le refus se fait A L'ENREGISTREMENT plutot qu'a la paie, meme discipline que
FLX-6 pour les correspondances de champs : accepter une categorie fausse et
la decouvrir sur un bulletin, c'est transformer une erreur de saisie en
erreur de paie."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.calendar import Holiday
from apps.core.services.workflow import attempt_transition
from apps.presence.models import PrsEmployee, PrsOvertime

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def holiday_on(tenant: Tenant, date: dt.date) -> Holiday | None:
    """Le jour ferie de cette societe a cette date, s'il y en a un.

    Par SOCIETE et pas par pays : une entreprise franche peut chomer des
    jours qu'une autre travaille, et une journee electorale ou un deuil
    national se saisit societe par societe."""
    return Holiday.objects.filter(tenant=tenant, date=date).first()


def record_overtime(
    employee: PrsEmployee,
    *,
    date: dt.date,
    hours: Decimal,
    rate_category: str,
    payroll_period: str = "",
) -> PrsOvertime:
    ferie = holiday_on(employee.tenant, date)
    if ferie is not None and rate_category != PrsOvertime.RATE_HOLIDAY:
        # **Le ferie l'emporte sur le dimanche**, et le cas n'est pas
        # theorique : Paques et la Pentecote tombent TOUJOURS un dimanche, et
        # quatre des Aid estimes de la decennie aussi. Laisser passer
        # `dimanche` paierait 1,40 la ou la loi dit 2,00.
        raise ValidationError(
            _(
                "Le %(date)s est un jour férié (%(nom)s) pour cette société : les heures "
                "y sont majorées de 100 %%, la catégorie doit être « %(attendue)s » et "
                "non « %(fournie)s »."
            )
            % {
                "date": date.isoformat(),
                "nom": ferie.name,
                "attendue": PrsOvertime.RATE_HOLIDAY,
                "fournie": rate_category,
            }
        )

    overtime = PrsOvertime(
        tenant=employee.tenant,
        employee=employee,
        date=date,
        hours=hours,
        rate_category=rate_category,
        payroll_period=payroll_period,
    )
    overtime.full_clean()
    overtime.save()
    return overtime


def validate_overtime(overtime: PrsOvertime, user: User) -> PrsOvertime:
    attempt_transition(overtime, "validate", user)
    overtime.validated_by = user
    overtime.save(update_fields=["state", "validated_by"])
    return overtime
