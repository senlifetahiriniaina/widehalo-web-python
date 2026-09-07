"""Un jour férié travaillé ne peut pas être déclaré en heures ordinaires.

`record_overtime` acceptait `rate_category` en paramètre libre : déclarer
des heures du 26 juin en `h_sup_30` passait sans un mot, et le bulletin les
payait 1,30 au lieu de 2,00. La catégorie et le calendrier ne se parlaient
pas.

Le refus se fait **à l'enregistrement** plutôt qu'à la paie — même
discipline que FLX-6 pour les correspondances de champs. Accepter une
catégorie fausse et la découvrir sur un bulletin, c'est transformer une
erreur de saisie en erreur de paie, un mois plus tard, sur la fiche d'un
salarié.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.services.calendar import declare_holiday
from apps.core.tests.utils import use_tenant
from apps.presence.models import PrsOvertime
from apps.presence.services.overtime import record_overtime
from apps.presence.tests.factories import PrsEmployeeFactory

pytestmark = pytest.mark.django_db

FETE_NATIONALE = dt.date(2026, 6, 26)


@pytest.fixture
def societe() -> Tenant:
    return Tenant.objects.create(code="PRS-FERIE", name="Fériés SARL")


def test_ordinary_overtime_is_refused_on_a_holiday(societe: Tenant) -> None:
    with use_tenant(societe.id):
        declare_holiday(societe, date=FETE_NATIONALE, name="Fete de l'Independance")
        employe = PrsEmployeeFactory(tenant=societe)

        with pytest.raises(ValidationError) as refus:
            record_overtime(
                employe,
                date=FETE_NATIONALE,
                hours=Decimal("4"),
                rate_category=PrsOvertime.RATE_H_SUP_30,
            )

    message = str(refus.value)
    assert FETE_NATIONALE.isoformat() in message, f"Le refus ne nomme pas la date : {message}"
    assert "Independance" in message, (
        "Le refus ne nomme pas le jour férié — l'utilisateur ne peut pas savoir "
        f"POURQUOI sa saisie est refusée : {message}"
    )


def test_the_holiday_beats_the_sunday(societe: Tenant) -> None:
    """**Le cas qui se présente vraiment.** Pâques et la Pentecôte tombent
    toujours un dimanche, et quatre des Aïd estimés de la décennie aussi.

    Déclarer ces heures en `dimanche` (1,40) paierait 30 % de moins que le
    férié (2,00). La règle est donc explicite : le férié l'emporte."""
    paques = dt.date(2026, 4, 5)
    assert paques.isoweekday() == 7, "Pâques 2026 doit bien être un dimanche."

    with use_tenant(societe.id):
        declare_holiday(societe, date=paques, name="Paques")
        employe = PrsEmployeeFactory(tenant=societe)

        with pytest.raises(ValidationError):
            record_overtime(
                employe,
                date=paques,
                hours=Decimal("6"),
                rate_category=PrsOvertime.RATE_SUNDAY,
            )

        accepte = record_overtime(
            employe,
            date=paques,
            hours=Decimal("6"),
            rate_category=PrsOvertime.RATE_HOLIDAY,
        )
        assert accepte.rate_category == PrsOvertime.RATE_HOLIDAY


def test_an_ordinary_day_accepts_any_category(societe: Tenant) -> None:
    """La contrepartie, sans laquelle la garde serait un refus généralisé
    déguisé en règle métier."""
    mardi_ordinaire = dt.date(2026, 6, 23)
    with use_tenant(societe.id):
        declare_holiday(societe, date=FETE_NATIONALE, name="Fete de l'Independance")
        employe = PrsEmployeeFactory(tenant=societe)
        ligne = record_overtime(
            employe,
            date=mardi_ordinaire,
            hours=Decimal("2"),
            rate_category=PrsOvertime.RATE_H_SUP_30,
        )
        assert ligne.rate_category == PrsOvertime.RATE_H_SUP_30


def test_one_company_s_holiday_never_constrains_another(societe: Tenant) -> None:
    """Le calendrier est par société — une entreprise franche peut chômer un
    jour qu'une autre travaille. Sans ce test, une garde qui interrogerait le
    calendrier sans filtrer la société passerait inaperçue tant qu'une seule
    société existe."""
    autre = Tenant.objects.create(code="PRS-FERIE-B", name="Autre SARL")
    with use_tenant(societe.id):
        declare_holiday(societe, date=FETE_NATIONALE, name="Fete de l'Independance")

    with use_tenant(autre.id):
        employe_b = PrsEmployeeFactory(tenant=autre)
        ligne = record_overtime(
            employe_b,
            date=FETE_NATIONALE,
            hours=Decimal("3"),
            rate_category=PrsOvertime.RATE_H_SUP_30,
        )
        assert ligne.rate_category == PrsOvertime.RATE_H_SUP_30
